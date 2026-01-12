import tkinter as tk
from tkinter import messagebox, ttk
import grpc
import json
import sys
import os
import random
import consul
from threading import Thread
import time

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import generated protobuf files
import protos.game_service_pb2 as game_pb2
import protos.game_service_pb2_grpc as game_pb2_grpc

class RPSClient:
    def __init__(self, root):
        self.root = root
        self.root.title("Rock Paper Scissors Online")
        self.root.geometry("600x700")
        self.root.resizable(False, False)
        
        # Load config
        with open('config.json', 'r') as f:
            self.config = json.load(f)
        
        # Game state
        self.client = None
        self.game_id = None
        self.player_id = ""
        self.polling = False
        self.current_server_url = None
        self.is_connected = False
        
        # Consul client
        self.consul_client = None
        
        # Connect to Consul and monitor game server
        self._connect_to_consul()
        
        # Create UI
        self._create_login_screen()
        
    def _connect_to_consul(self):
        """Connect to Consul and start monitoring game server leader"""
        try:
            consul_host = self.config['consul']['host']
            consul_port = self.config['consul']['port']
            self.consul_client = consul.Consul(host=consul_host, port=consul_port)
            print(f"[Client] Connected to Consul at {consul_host}:{consul_port}")
            
            # Start monitoring game server leader
            Thread(target=self._monitor_game_server, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Consul Error", f"Failed to connect to Consul: {e}")
    
    def _monitor_game_server(self):
        """Monitor game server leader from Consul"""
        while True:
            try:
                if self.consul_client:
                    index, data = self.consul_client.kv.get("service/rps-game/leader")
                    if data:
                        leader_url = data['Value'].decode('utf-8')
                        if leader_url != self.current_server_url:
                            self.current_server_url = leader_url
                            print(f"[Client] Game Server Leader: {leader_url}")
                            self._connect_to_server(leader_url)
                    else:
                        self.current_server_url = None
                        self.client = None
                        self.is_connected = False
                        self._set_connection_status(False)
                        
            except Exception as e:
                print(f"[Server Monitor Error] {e}")
                self.is_connected = False
                self._set_connection_status(False)
            
            time.sleep(2)
    
    def _connect_to_server(self, server_url):
        """Connect to game server"""
        try:
            # Remove http:// prefix if present
            server_addr = server_url.replace('http://', '')
            channel = grpc.insecure_channel(server_addr)
            self.client = game_pb2_grpc.GameServiceStub(channel)
            print(f"[Client] Connected to game server at {server_addr}")
            self.is_connected = True
            self._set_connection_status(True)
        except Exception as e:
            print(f"[Connection Error] {e}")
            self.client = None
            self.is_connected = False
            self._set_connection_status(False)
    
    def _wait_for_server(self):
        """Wait for server to be available"""
        for i in range(10):
            if self.client:
                return True
            time.sleep(0.5)
        return False
    
    def _create_login_screen(self):
        """Create login screen"""
        self.login_frame = tk.Frame(self.root, bg="#f0f0f0")
        self.login_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title = tk.Label(
            self.login_frame,
            text="Rock Paper\nScissors\nOnline",
            font=("Arial", 48, "bold"),
            bg="#f0f0f0",
            fg="#2c3e50"
        )
        title.pack(pady=50)
        
        # Nickname input
        tk.Label(
            self.login_frame,
            text="Enter your nickname:",
            font=("Arial", 12),
            bg="#f0f0f0"
        ).pack(pady=10)
        
        self.nickname_entry = tk.Entry(
            self.login_frame,
            font=("Arial", 14),
            width=20,
            justify="center"
        )
        self.nickname_entry.pack(pady=10)
        
        # Login button
        login_btn = tk.Button(
            self.login_frame,
            text="ENTER GAME",
            font=("Arial", 14, "bold"),
            bg="#3498db",
            fg="white",
            width=20,
            height=2,
            command=self._on_login
        )
        login_btn.pack(pady=20)
        
        # Status label
        self.login_status = tk.Label(
            self.login_frame,
            text="Waiting for server...",
            font=("Arial", 10),
            bg="#f0f0f0",
            fg="#7f8c8d"
        )
        self.login_status.pack(pady=10)
        
        # Update status
        self._update_login_status()
    
    def _update_login_status(self):
        """Update login status label"""
        if self.client and self.is_connected:
            self.login_status.config(text="✓ Connected to server", fg="#27ae60")
        else:
            self.login_status.config(text="⏳ Waiting for server...", fg="#e67e22")
        
        self.root.after(1000, self._update_login_status)
    
    def _on_login(self):
        """Handle login"""
        nickname = self.nickname_entry.get().strip()
        if not nickname:
            messagebox.showwarning("Invalid Input", "Please enter a nickname")
            return
        
        if not self._wait_for_server() or not self.is_connected:
            messagebox.showerror("Error", "Game server not available. Please wait...")
            return
        
        self.player_id = nickname
        
        # Check for existing session
        try:
            response = self.client.CheckSession(
                game_pb2.CheckRequest(player_id=self.player_id)
            )
            
            if response.exists:
                # Rejoin existing game
                self.game_id = response.game_id
                # Destroy login frame before showing game screen
                self.login_frame.destroy()
                self._show_game_screen()
                self._start_polling()
            else:
                # Show room selection
                self._show_room_screen()
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to check session: {e}")
    
    def _show_room_screen(self):
        """Show room creation/join screen"""
        self.login_frame.destroy()
        
        self.room_frame = tk.Frame(self.root, bg="#f0f0f0")
        self.room_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(
            self.room_frame,
            text="Game Lobby",
            font=("Arial", 32, "bold"),
            bg="#f0f0f0",
            fg="#2c3e50"
        ).pack(pady=50)
        
        # Create room button
        create_btn = tk.Button(
            self.room_frame,
            text="Create New Room",
            font=("Arial", 14),
            bg="#27ae60",
            fg="white",
            width=20,
            height=2,
            command=self._create_room
        )
        create_btn.pack(pady=20)
        
        # Join room
        tk.Label(
            self.room_frame,
            text="Or enter Room ID:",
            font=("Arial", 12),
            bg="#f0f0f0"
        ).pack(pady=10)
        
        self.room_id_entry = tk.Entry(
            self.room_frame,
            font=("Arial", 14),
            width=15,
            justify="center"
        )
        self.room_id_entry.pack(pady=10)
        
        join_btn = tk.Button(
            self.room_frame,
            text="Join Room",
            font=("Arial", 14),
            bg="#3498db",
            fg="white",
            width=20,
            height=2,
            command=self._join_room
        )
        join_btn.pack(pady=20)
    
    def _create_room(self):
        """Create a new room"""
        room_id = str(random.randint(1000, 9999))
        self._start_game(room_id, is_join=False)
    
    def _join_room(self):
        """Join existing room"""
        room_id = self.room_id_entry.get().strip()
        if len(room_id) != 4 or not room_id.isdigit():
            messagebox.showwarning("Invalid Input", "Room ID must be 4 digits")
            return
        
        self._start_game(room_id, is_join=True)
    
    def _start_game(self, room_id, is_join):
        """Start or join a game"""
        if not self._wait_for_server() or not self.is_connected:
            messagebox.showerror("Error", "Game server not available")
            return
        
        try:
            response = self.client.CreateGame(
                game_pb2.CreateRequest(
                    player_id=f"{self.player_id}|{room_id}",
                    is_join_only=is_join
                )
            )
            
            if response.error:
                if response.error == "ROOM_NOT_FOUND":
                    messagebox.showerror("Error", f"Room #{room_id} not found!")
                elif response.error == "ROOM_FULL":
                    messagebox.showerror("Error", f"Room #{room_id} is full!")
                else:
                    messagebox.showerror("Error", response.error)
                return
            
            self.game_id = response.game_id
            self.room_frame.destroy()
            self._show_game_screen()
            self._start_polling()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start game: {e}")
    
    def _show_game_screen(self):
        """Show main game screen"""
        self.game_frame = tk.Frame(self.root, bg="#ecf0f1")
        self.game_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header = tk.Frame(self.game_frame, bg="#34495e", height=100)
        header.pack(fill=tk.X)
        
        self.info_label = tk.Label(
            header,
            text="",
            font=("Arial", 11, "bold"),
            bg="#34495e",
            fg="white",
            justify="left"
        )
        self.info_label.pack(side=tk.LEFT, padx=20, pady=10)
        
        # Exit button
        exit_btn = tk.Button(
            header,
            text="Exit",
            font=("Arial", 10),
            bg="#e74c3c",
            fg="white",
            command=self._exit_game
        )
        exit_btn.pack(side=tk.RIGHT, padx=20, pady=10)
        
        # Status bar
        self.status_label = tk.Label(
            self.game_frame,
            text="",
            font=("Arial", 14, "bold"),
            bg="#3498db",
            fg="white",
            height=2
        )
        self.status_label.pack(fill=tk.X)
        
        # Score display
        score_frame = tk.Frame(self.game_frame, bg="#ecf0f1")
        score_frame.pack(pady=20)
        
        self.score_label = tk.Label(
            score_frame,
            text="",
            font=("Arial", 18, "bold"),
            bg="#ecf0f1",
            fg="#2c3e50"
        )
        self.score_label.pack()
        
        # Result display
        self.result_label = tk.Label(
            self.game_frame,
            text="",
            font=("Arial", 16),
            bg="#ecf0f1",
            fg="#e74c3c",
            wraplength=500
        )
        self.result_label.pack(pady=20)
        
        # Choice buttons
        choice_frame = tk.Frame(self.game_frame, bg="#ecf0f1")
        choice_frame.pack(pady=30)
        
        tk.Label(
            choice_frame,
            text="Make your choice:",
            font=("Arial", 14),
            bg="#ecf0f1"
        ).pack(pady=10)
        
        buttons_frame = tk.Frame(choice_frame, bg="#ecf0f1")
        buttons_frame.pack()
        
        # Rock button
        self.rock_btn = tk.Button(
            buttons_frame,
            text="🪨\nROCK",
            font=("Arial", 16, "bold"),
            bg="#95a5a6",
            fg="white",
            width=10,
            height=4,
            command=lambda: self._make_choice("rock")
        )
        self.rock_btn.grid(row=0, column=0, padx=10)
        
        # Paper button
        self.paper_btn = tk.Button(
            buttons_frame,
            text="📄\nPAPER",
            font=("Arial", 16, "bold"),
            bg="#3498db",
            fg="white",
            width=10,
            height=4,
            command=lambda: self._make_choice("paper")
        )
        self.paper_btn.grid(row=0, column=1, padx=10)
        
        # Scissors button
        self.scissors_btn = tk.Button(
            buttons_frame,
            text="✂️\nSCISSORS",
            font=("Arial", 16, "bold"),
            bg="#e74c3c",
            fg="white",
            width=10,
            height=4,
            command=lambda: self._make_choice("scissors")
        )
        self.scissors_btn.grid(row=0, column=2, padx=10)
        
        # Next round button
        self.next_round_btn = tk.Button(
            self.game_frame,
            text="Next Round",
            font=("Arial", 14, "bold"),
            bg="#27ae60",
            fg="white",
            width=20,
            height=2,
            command=self._next_round,
            state=tk.DISABLED
        )
        self.next_round_btn.pack(pady=20)
    
    def _make_choice(self, choice):
        """Player makes a choice"""
        if not self.client or not self.is_connected:
            messagebox.showerror("Error", "Not connected to server")
            return
        
        try:
            response = self.client.MakeMove(
                game_pb2.MoveRequest(
                    game_id=self.game_id,
                    player_id=self.player_id,
                    choice=choice
                )
            )
            
            if response.error:
                messagebox.showerror("Error", response.error)
            else:
                self._update_ui(response)
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to make move: {e}")
    
    def _next_round(self):
        """Start next round"""
        if not self.client or not self.is_connected:
            return
        
        try:
            response = self.client.ResetGame(
                game_pb2.StateRequest(
                    game_id=self.game_id,
                    player_id=self.player_id
                )
            )
            
            self._update_ui(response)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset game: {e}")
    
    def _start_polling(self):
        """Start polling for game state updates"""
        self.polling = True
        
        def poll():
            while self.polling:
                try:
                    if self.client and self.is_connected:
                        response = self.client.GetState(
                            game_pb2.StateRequest(
                                game_id=self.game_id,
                                player_id=self.player_id
                            )
                        )
                        
                        if not response.error:
                            self.root.after(0, lambda: self._update_ui(response))
                    
                except Exception as e:
                    print(f"[Polling Error] {e}")
                    self.is_connected = False
                    self.root.after(0, lambda: self._set_connection_status(False))
                
                time.sleep(2)
        
        Thread(target=poll, daemon=True).start()
    
    def _update_ui(self, response):
        """Update UI with game state"""
        # Check connection status first
        if not self.is_connected:
            self.status_label.config(text="Waiting for connection...", bg="#e74c3c", fg="white")
            self._disable_buttons()
            return
        
        # Update info
        self.info_label.config(
            text=f"Player: {self.player_id}\nRoom: #{response.game_id}\n" +
                 f"Players: {response.player1} vs {response.player2}"
        )
        
        # Update score
        self.score_label.config(
            text=f"Score: {response.player1_score} - {response.player2_score}"
        )
        
        # Update status
        if response.status == "waiting":
            self.status_label.config(text="Waiting for opponent...", bg="#f39c12", fg="white")
            self._disable_buttons()
        elif response.status == "ready":
            # Check if current player has made a choice
            is_player1 = (self.player_id == response.player1)
            my_choice = response.player1_choice if is_player1 else response.player2_choice
            
            if my_choice == "waiting":
                self.status_label.config(text="Make your choice!", bg="#27ae60", fg="white")
                self._enable_buttons()
            else:
                self.status_label.config(text="Waiting for opponent's choice...", bg="#f39c12", fg="white")
                self._disable_buttons()
        else:
            # Round finished
            self.status_label.config(text="Round Complete!", bg="#3498db", fg="white")
            self._disable_buttons()
            self.next_round_btn.config(state=tk.NORMAL)
        
        # Update result
        self.result_label.config(text=response.round_result)
    
    def _enable_buttons(self):
        """Enable choice buttons"""
        if self.is_connected:
            self.rock_btn.config(state=tk.NORMAL)
            self.paper_btn.config(state=tk.NORMAL)
            self.scissors_btn.config(state=tk.NORMAL)
            self.next_round_btn.config(state=tk.DISABLED)
    
    def _disable_buttons(self):
        """Disable choice buttons"""
        self.rock_btn.config(state=tk.DISABLED)
        self.paper_btn.config(state=tk.DISABLED)
        self.scissors_btn.config(state=tk.DISABLED)
    
    def _set_connection_status(self, connected):
        """Update UI based on connection status"""
        def update():
            if not connected:
                # Show red "Waiting for connection..." message
                if hasattr(self, 'status_label'):
                    self.status_label.config(
                        text="Waiting for connection...",
                        bg="#e74c3c",
                        fg="white"
                    )
                if hasattr(self, 'rock_btn'):
                    self._disable_buttons()
            else:
                # Connection restored
                if hasattr(self, 'status_label') and self.game_id:
                    # Will be updated by next poll
                    pass
        
        if hasattr(self, 'root'):
            self.root.after(0, update)
    
    def _exit_game(self):
        """Exit the game"""
        if messagebox.askyesno("Exit", "Are you sure you want to exit?"):
            try:
                self.polling = False
                if self.client:
                    self.client.ExitGame(
                        game_pb2.ExitRequest(
                            game_id=self.game_id,
                            player_id=self.player_id
                        )
                    )
            except:
                pass
            
            self.root.quit()

def main():
    root = tk.Tk()
    app = RPSClient(root)
    root.mainloop()

if __name__ == '__main__':
    main()
