import grpc
from concurrent import futures
import json
import sys
import os
import consul
import socket
import time
import argparse
from threading import Thread

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import generated protobuf files
import protos.game_service_pb2 as game_pb2
import protos.game_service_pb2_grpc as game_pb2_grpc
import protos.orm_pb2 as orm_pb2
import protos.orm_pb2_grpc as orm_pb2_grpc

from game_server.game_logic import RockPaperScissorsGame

def get_local_ip():
    """Get local IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

class GameServiceImpl(game_pb2_grpc.GameServiceServicer):
    def __init__(self, config, consul_client):
        self.config = config
        self.consul_client = consul_client
        self.orm_client = None
        self.current_orm_url = None
        
        # Start monitoring ORM leader
        Thread(target=self._monitor_orm_leader, daemon=True).start()
    
    def _monitor_orm_leader(self):
        """Monitor ORM leader from Consul"""
        while True:
            try:
                index, data = self.consul_client.kv.get("service/rps-orm/leader")
                if data:
                    leader_url = data['Value'].decode('utf-8')
                    if leader_url != self.current_orm_url:
                        self.current_orm_url = leader_url
                        print(f"[Game Server] ORM Leader: {leader_url}")
                        
                        # Connect to new ORM leader
                        channel = grpc.insecure_channel(leader_url.replace('http://', ''))
                        self.orm_client = orm_pb2_grpc.OrmStub(channel)
                else:
                    self.orm_client = None
                    self.current_orm_url = None
                    
            except Exception as e:
                print(f"[ORM Monitor Error] {e}")
            
            time.sleep(1)
    
    def _wait_for_orm(self):
        """Wait for ORM client to be available"""
        for i in range(10):
            if self.orm_client:
                return self.orm_client
            time.sleep(0.5)
        raise Exception("ORM service not available")
    
    def CheckSession(self, request, context):
        """Check if player has an active session"""
        try:
            orm = self._wait_for_orm()
            response = orm.CheckSession(
                orm_pb2.CheckSessionRequest(player_id=request.player_id)
            )
            return game_pb2.CheckResponse(
                exists=response.exists,
                game_id=response.game_id
            )
        except Exception as e:
            print(f"[Game Server Error] CheckSession: {e}")
            return game_pb2.CheckResponse(exists=False, game_id="")
    
    def CreateGame(self, request, context):
        """Create or join a game"""
        try:
            # Parse player_id format: "Nickname|RoomID"
            parts = request.player_id.split('|')
            if len(parts) < 2:
                return game_pb2.GameResponse(error="ID_ERR")
            
            nickname = parts[0]
            room_id = parts[1]
            
            # Try to load existing game
            game = self._load_game(room_id)
            
            if game is None:
                # Game doesn't exist
                if request.is_join_only:
                    return game_pb2.GameResponse(error="ROOM_NOT_FOUND")
                
                # Create new game
                game = RockPaperScissorsGame()
                game.player1 = nickname
                game.status = "waiting"
            else:
                # Game exists - try to join
                if game.player1 == nickname or game.player2 == nickname:
                    # Player already in game
                    pass
                elif not game.player1:
                    game.player1 = nickname
                elif not game.player2:
                    game.player2 = nickname
                    game.status = "ready"
                else:
                    return game_pb2.GameResponse(error="ROOM_FULL")
            
            # Save game state
            self._save_game(room_id, game)
            
            return self._map_to_response(room_id, game)
            
        except Exception as e:
            print(f"[Game Server Error] CreateGame: {e}")
            return game_pb2.GameResponse(error=str(e))
    
    def MakeMove(self, request, context):
        """Player makes a move"""
        try:
            game = self._load_game(request.game_id)
            if game is None:
                return game_pb2.GameResponse(error="ROOM_ERR")
            
            # Validate and make move
            if not game.can_make_move(request.player_id):
                return game_pb2.GameResponse(error="INVALID_MOVE")
            
            if not game.make_move(request.player_id, request.choice):
                return game_pb2.GameResponse(error="INVALID_CHOICE")
            
            # Save updated game state
            self._save_game(request.game_id, game)
            
            return self._map_to_response(request.game_id, game)
            
        except Exception as e:
            print(f"[Game Server Error] MakeMove: {e}")
            return game_pb2.GameResponse(error=str(e))
    
    def GetState(self, request, context):
        """Get current game state"""
        try:
            game = self._load_game(request.game_id)
            if game is None:
                return game_pb2.GameResponse(error="NOT_FOUND")
            
            return self._map_to_response(request.game_id, game)
            
        except Exception as e:
            print(f"[Game Server Error] GetState: {e}")
            return game_pb2.GameResponse(error=str(e))
    
    def ResetGame(self, request, context):
        """Reset game for new round"""
        try:
            game = self._load_game(request.game_id)
            if game is None:
                return game_pb2.GameResponse(error="NOT_FOUND")
            
            game.reset_round()
            self._save_game(request.game_id, game)
            
            return self._map_to_response(request.game_id, game)
            
        except Exception as e:
            print(f"[Game Server Error] ResetGame: {e}")
            return game_pb2.GameResponse(error=str(e))
    
    def ExitGame(self, request, context):
        """Player exits game"""
        try:
            orm = self._wait_for_orm()
            response = orm.ExitGame(
                orm_pb2.ExitGameRequest(
                    game_id=request.game_id,
                    player_id=request.player_id
                )
            )
            return game_pb2.ExitResponse(success=response.success)
            
        except Exception as e:
            print(f"[Game Server Error] ExitGame: {e}")
            return game_pb2.ExitResponse(success=False)
    
    def _load_game(self, game_id):
        """Load game from database"""
        try:
            orm = self._wait_for_orm()
            response = orm.Load(orm_pb2.LoadRequest(game_id=game_id))
            if response.success:
                game = RockPaperScissorsGame()
                game.player1 = response.game.player1
                game.player2 = response.game.player2
                game.player1_choice = response.game.player1_choice
                game.player2_choice = response.game.player2_choice
                game.status = response.game.status
                game.player1_score = response.game.player1_score
                game.player2_score = response.game.player2_score
                return game
            return None
        except Exception as e:
            print(f"[Game Server Error] Load: {e}")
            return None
    
    def _save_game(self, game_id, game):
        """Save game to database"""
        try:
            orm = self._wait_for_orm()
            orm_game = orm_pb2.Game(
                player1=game.player1,
                player2=game.player2,
                player1_choice=game.player1_choice,
                player2_choice=game.player2_choice,
                status=game.status,
                player1_score=game.player1_score,
                player2_score=game.player2_score
            )
            
            orm.Save(
                orm_pb2.SaveRequest(game=orm_game, game_id=game_id)
            )
        except Exception as e:
            print(f"[Game Server Error] Save: {e}")
    
    def _map_to_response(self, game_id, game):
        """Map game object to gRPC response"""
        # Hide opponent's choice if round is not finished
        p1_choice = game.player1_choice
        p2_choice = game.player2_choice
        
        if game.status in ["ready", "waiting"]:
            # Don't reveal choices until both players have chosen
            if game.player1_choice != "waiting" and game.player2_choice == "waiting":
                p1_choice = "chosen"
            elif game.player2_choice != "waiting" and game.player1_choice == "waiting":
                p2_choice = "chosen"
        
        return game_pb2.GameResponse(
            game_id=game_id,
            player1=game.player1,
            player2=game.player2,
            player1_choice=p1_choice,
            player2_choice=p2_choice,
            status=game.status,
            current_player_id="",  # Not used in RPS
            player1_score=game.player1_score,
            player2_score=game.player2_score,
            round_result=game.get_round_result()
        )

def leader_election_loop(consul_client, service_id, my_url, config):
    """Consul leader election loop for game server"""
    leader_key = "service/rps-game/leader"
    
    while True:
        session_id = None
        try:
            # Create session
            session_id = consul_client.session.create(
                name=f"game-leader-{config['server']['port']}",
                ttl=10,
                lock_delay=0,
                behavior='delete'
            )
            
            # Try to acquire leadership
            acquired = consul_client.kv.put(
                leader_key,
                my_url,
                acquire=session_id
            )
            
            if acquired:
                print(f"[{time.strftime('%H:%M:%S')}] [Leader] I am the GAME SERVER LEADER")
                
                # Maintain leadership
                while True:
                    try:
                        consul_client.session.renew(session_id)
                        time.sleep(1)
                        
                        # Check if still leader
                        index, data = consul_client.kv.get(leader_key)
                        if not data or data.get('Session') != session_id:
                            print(f"[{time.strftime('%H:%M:%S')}] [Leader] Leadership LOST")
                            break
                    except:
                        break
            else:
                # Not leader, wait
                time.sleep(1)
                
        except Exception as e:
            print(f"[Leader Election Error] {e}")
            time.sleep(2)
        finally:
            if session_id:
                try:
                    consul_client.session.destroy(session_id)
                except:
                    pass

def serve():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='RPS Game Server')
    parser.add_argument('--port', type=int, help='Port to run the server on')
    parser.add_argument('--consul-host', type=str, help='Consul host address')
    parser.add_argument('--consul-port', type=int, help='Consul port')
    args = parser.parse_args()
    
    # Load config
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    # Override config with command line arguments
    if args.port:
        config['server']['port'] = args.port
    if args.consul_host:
        config['consul']['host'] = args.consul_host
    if args.consul_port:
        config['consul']['port'] = args.consul_port
    
    # Get local IP and port
    host_ip = get_local_ip()
    port = config['server']['port']
    my_url = f"http://{host_ip}:{port}"
    
    print(f"[Game Server] Configuration:")
    print(f"  - Port: {port}")
    print(f"  - Consul: {config['consul']['host']}:{config['consul']['port']}")
    
    # Connect to Consul
    consul_host = config['consul']['host']
    consul_port = config['consul']['port']
    consul_client = consul.Consul(host=consul_host, port=consul_port)
    
    # Create gRPC server
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    game_pb2_grpc.add_GameServiceServicer_to_server(
        GameServiceImpl(config, consul_client),
        server
    )
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    
    print(f"[Game Server] Started on {my_url}")
    
    # Register service in Consul
    try:
        service_id = f"rps-game-{port}"
        consul_client.agent.service.register(
            name="rps-game-service",
            service_id=service_id,
            address=host_ip,
            port=port,
            check=consul.Check.tcp(host_ip, port, interval="2s")
        )
        
        print(f"[Consul] Registered as {service_id}")
        
        # Start leader election in background
        Thread(target=leader_election_loop, args=(consul_client, service_id, my_url, config), daemon=True).start()
        
    except Exception as e:
        print(f"[Consul Error] {e}")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("[Game Server] Shutting down...")
        server.stop(0)

if __name__ == '__main__':
    serve()
