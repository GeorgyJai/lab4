class RockPaperScissorsGame:
    """Game logic for Rock Paper Scissors"""
    
    def __init__(self):
        self.player1 = ""
        self.player2 = ""
        self.player1_choice = "waiting"
        self.player2_choice = "waiting"
        self.status = "waiting"  # waiting, ready, player1_won, player2_won, draw
        self.player1_score = 0
        self.player2_score = 0
    
    def set_players(self, player1, player2):
        self.player1 = player1
        self.player2 = player2
        if player1 and player2:
            self.status = "ready"
    
    def make_move(self, player_id, choice):
        """
        Player makes a choice: rock, paper, or scissors
        Returns True if move was valid
        """
        if choice not in ["rock", "paper", "scissors"]:
            return False
        
        if player_id == self.player1:
            self.player1_choice = choice
        elif player_id == self.player2:
            self.player2_choice = choice
        else:
            return False
        
        # Check if both players have made their choices
        if self.player1_choice != "waiting" and self.player2_choice != "waiting":
            self._evaluate_round()
        
        return True
    
    def _evaluate_round(self):
        """Evaluate the round and determine winner"""
        p1 = self.player1_choice
        p2 = self.player2_choice
        
        if p1 == p2:
            self.status = "draw"
        elif (p1 == "rock" and p2 == "scissors") or \
             (p1 == "scissors" and p2 == "paper") or \
             (p1 == "paper" and p2 == "rock"):
            self.status = "player1_won"
            self.player1_score += 1
        else:
            self.status = "player2_won"
            self.player2_score += 1
    
    def reset_round(self):
        """Reset for next round, keeping scores"""
        self.player1_choice = "waiting"
        self.player2_choice = "waiting"
        if self.player1 and self.player2:
            self.status = "ready"
        else:
            self.status = "waiting"
    
    def get_round_result(self):
        """Get human-readable result of the round"""
        if self.status == "draw":
            return f"Draw! Both chose {self.player1_choice}"
        elif self.status == "player1_won":
            return f"{self.player1} wins! {self.player1_choice} beats {self.player2_choice}"
        elif self.status == "player2_won":
            return f"{self.player2} wins! {self.player2_choice} beats {self.player1_choice}"
        elif self.status == "ready":
            return "Make your choice!"
        else:
            return "Waiting for opponent..."
    
    def is_player_in_game(self, player_id):
        """Check if player is in this game"""
        return player_id == self.player1 or player_id == self.player2
    
    def can_make_move(self, player_id):
        """Check if player can make a move"""
        if not self.is_player_in_game(player_id):
            return False
        
        if self.status not in ["ready", "waiting"]:
            return False
        
        # Check if player already made a choice this round
        if player_id == self.player1 and self.player1_choice != "waiting":
            return False
        if player_id == self.player2 and self.player2_choice != "waiting":
            return False
        
        return True
