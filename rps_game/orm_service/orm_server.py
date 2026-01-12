import grpc
from concurrent import futures
import psycopg2
import json
import sys
import os
import time
import consul
import socket
import argparse
from threading import Thread

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import generated protobuf files (will be generated later)
import protos.orm_pb2 as orm_pb2
import protos.orm_pb2_grpc as orm_pb2_grpc

from orm_service.db_init import initialize

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

class OrmService(orm_pb2_grpc.OrmServicer):
    def __init__(self, config):
        self.config = config
        
    def get_connection(self):
        return psycopg2.connect(
            host=self.config['database']['host'],
            port=self.config['database']['port'],
            user=self.config['database']['user'],
            password=self.config['database']['password'],
            database=self.config['database']['database']
        )
    
    def CheckSession(self, request, context):
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT game_id FROM games WHERE player1 = %s OR player2 = %s LIMIT 1",
                (request.player_id, request.player_id)
            )
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return orm_pb2.CheckSessionResponse(exists=True, game_id=result[0])
            else:
                return orm_pb2.CheckSessionResponse(exists=False, game_id="")
        except Exception as e:
            print(f"[ORM Error] CheckSession: {e}")
            return orm_pb2.CheckSessionResponse(exists=False, game_id="")
    
    def ExitGame(self, request, context):
        try:
            # Load game first
            load_resp = self.Load(orm_pb2.LoadRequest(game_id=request.game_id), context)
            
            if load_resp.success:
                game = load_resp.game
                
                # Remove player
                if game.player1 == request.player_id:
                    game.player1 = ""
                elif game.player2 == request.player_id:
                    game.player2 = ""
                
                # If both players left, delete the game
                if not game.player1 and not game.player2:
                    conn = self.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM games WHERE game_id = %s", (request.game_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                else:
                    # Save updated game
                    self.Save(orm_pb2.SaveRequest(game=game, game_id=request.game_id), context)
            
            return orm_pb2.ExitGameResponse(success=True)
        except Exception as e:
            print(f"[ORM Error] ExitGame: {e}")
            return orm_pb2.ExitGameResponse(success=False)
    
    def Load(self, request, context):
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT player1, player2, player1_choice, player2_choice, 
                   status, player1_score, player2_score 
                   FROM games WHERE game_id = %s""",
                (request.game_id,)
            )
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                game = orm_pb2.Game(
                    player1=result[0] or "",
                    player2=result[1] or "",
                    player1_choice=result[2] or "",
                    player2_choice=result[3] or "",
                    status=result[4] or "",
                    player1_score=result[5] or 0,
                    player2_score=result[6] or 0
                )
                return orm_pb2.LoadResponse(success=True, game=game)
            else:
                return orm_pb2.LoadResponse(success=False)
        except Exception as e:
            print(f"[ORM Error] Load: {e}")
            return orm_pb2.LoadResponse(success=False)
    
    def Save(self, request, context):
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO games (game_id, player1, player2, player1_choice, 
                                   player2_choice, status, player1_score, player2_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (game_id) DO UPDATE SET
                    player1 = EXCLUDED.player1,
                    player2 = EXCLUDED.player2,
                    player1_choice = EXCLUDED.player1_choice,
                    player2_choice = EXCLUDED.player2_choice,
                    status = EXCLUDED.status,
                    player1_score = EXCLUDED.player1_score,
                    player2_score = EXCLUDED.player2_score
            """, (
                request.game_id,
                request.game.player1,
                request.game.player2,
                request.game.player1_choice,
                request.game.player2_choice,
                request.game.status,
                request.game.player1_score,
                request.game.player2_score
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return orm_pb2.SaveResponse(success=True)
        except Exception as e:
            print(f"[ORM Error] Save: {e}")
            return orm_pb2.SaveResponse(success=False)

def leader_election_loop(consul_client, service_id, my_url, config):
    """Consul leader election loop"""
    leader_key = "service/rps-orm/leader"
    
    while True:
        session_id = None
        try:
            # Create session
            session_id = consul_client.session.create(
                name=f"orm-leader-{config['orm']['port']}",
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
                print(f"[{time.strftime('%H:%M:%S')}] [Leader] I am the ORM LEADER")
                
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
    parser = argparse.ArgumentParser(description='RPS ORM Server')
    parser.add_argument('--port', type=int, help='Port to run the server on')
    parser.add_argument('--consul-host', type=str, help='Consul host address')
    parser.add_argument('--consul-port', type=int, help='Consul port')
    args = parser.parse_args()
    
    # Load config
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    # Override config with command line arguments
    if args.port:
        config['orm']['port'] = args.port
    if args.consul_host:
        config['consul']['host'] = args.consul_host
    if args.consul_port:
        config['consul']['port'] = args.consul_port
    
    # Initialize database
    initialize()
    
    # Get local IP and port
    host_ip = get_local_ip()
    port = config['orm']['port']
    my_url = f"http://{host_ip}:{port}"
    
    print(f"[ORM Server] Configuration:")
    print(f"  - Port: {port}")
    print(f"  - Consul: {config['consul']['host']}:{config['consul']['port']}")
    
    # Create gRPC server
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    orm_pb2_grpc.add_OrmServicer_to_server(OrmService(config), server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    
    print(f"[ORM Server] Started on {my_url}")
    
    # Connect to Consul
    try:
        consul_host = config['consul']['host']
        consul_port = config['consul']['port']
        consul_client = consul.Consul(host=consul_host, port=consul_port)
        
        # Register service
        service_id = f"rps-orm-{port}"
        consul_client.agent.service.register(
            name="rps-orm-service",
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
        print("[ORM Server] Shutting down...")
        server.stop(0)

if __name__ == '__main__':
    serve()
