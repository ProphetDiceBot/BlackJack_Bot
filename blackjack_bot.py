import cv2
import mss
import numpy as np
import pytesseract
import time
import pyautogui
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import Qt
import sys
import re

# Global variables for Hi-Lo counting system
running_count = 0
true_count = 0
decks_remaining = 4.0  # Initial number of decks in the shoe

# Card values for Hi-Lo counting system
card_values = {
    "2": 1, "3": 1, "4": 1, "5": 1, "6": 1,
    "7": 0, "8": 0, "9": 0, "10": -1, "J": -1, "Q": -1, "K": -1, "A": -1
}

class BlackjackBot:
    def __init__(self):
        self.sct = mss.mss()
        # Define screen region for the entire game window (based on 720x1280 resolution from screenshot)
        self.screen_region = {"top": 0, "left": 0, "width": 720, "height": 1280}

        # Define regions of interest (ROI) for player's hand and dealer's upcard
        # Adjusted based on the screenshot layout (player's hand: 7H, 3D; dealer's upcard: 5D)
        self.player_hand_roi = {"top": 600, "left": 260, "width": 200, "height": 150}  # Around player's cards
        self.dealer_card_roi = {"top": 300, "left": 300, "width": 100, "height": 100}  # Around dealer's upcard

    def capture_screen(self, region=None):
        """Capture a specific region of the screen."""
        try:
            region = region if region else self.screen_region
            screenshot = self.sct.grab(region)
            img = np.array(screenshot)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return img
        except Exception as e:
            print(f"Screen capture error: {e}")
            return None

    def preprocess_image(self, img):
        """Preprocess the image for better OCR detection."""
        if img is None:
            return None
        # Apply Gaussian blur and Otsu's thresholding for better contrast
        img = cv2.GaussianBlur(img, (5, 5), 0)
        _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return img

    def detect_cards(self, img):
        """Detect card values from the image using OCR."""
        if img is None:
            return []
        try:
            # Configure Tesseract for better card detection
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=23456789TJQKA'
            text = pytesseract.image_to_string(img, config=custom_config)
            print(f"Detected text: {text}")  # Debugging: Remove in production

            # Split text by whitespace to handle "10" and other card values
            detected_parts = text.upper().split()
            detected_cards = []
            for part in detected_parts:
                # Handle "10" explicitly
                if part == "10" or part in card_values:
                    detected_cards.append(part)
                    # Update decks remaining (assuming 52 cards per deck)
                    global decks_remaining
                    decks_remaining = max(0.25, decks_remaining - (1/52))
            return detected_cards
        except Exception as e:
            print(f"OCR error: {e}")
            return []

    def detect_hand(self, roi):
        """Detect cards in a specific region (player's hand or dealer's upcard)."""
        hand_img = self.capture_screen(roi)
        if hand_img is None:
            return []
        processed_img = self.preprocess_image(hand_img)
        cards = self.detect_cards(processed_img)
        return cards

    def calculate_hand_value(self, cards):
        """Calculate the total value of a hand, handling aces."""
        if not cards:
            return 0, False  # Total value, has_ace
        total = 0
        has_ace = False
        for card in cards:
            if card == 'A':
                has_ace = True
                total += 11
            elif card in ['K', 'Q', 'J', '10']:
                total += 10
            else:
                total += int(card)
        
        # Adjust for aces if total > 21
        if total > 21 and has_ace:
            total -= 10
        return total, has_ace

    def update_count(self, detected_cards):
        """Update the running and true counts based on detected cards."""
        global running_count, true_count, decks_remaining
        for card in detected_cards:
            running_count += card_values[card]
        true_count = running_count / max(0.25, decks_remaining)

    def get_bet_size(self, tc):
        """Determine bet size based on true count."""
        if tc <= 0:
            return 10  # Minimum bet
        elif tc <= 1:
            return 20
        elif tc <= 2:
            return 40
        elif tc <= 3:
            return 60
        elif tc <= 4:
            return 80
        else:
            return 100

class BlackjackOverlay(QtWidgets.QWidget):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.init_ui()

    def init_ui(self):
        """Initialize the GUI overlay."""
        self.setWindowTitle("Blackjack Assistant")
        self.setGeometry(50, 50, 300, 200)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Layout
        layout = QtWidgets.QVBoxLayout()
        
        self.info_label = QtWidgets.QLabel("Waiting for game...")
        self.info_label.setFont(QtGui.QFont("Arial", 12))
        layout.addWidget(self.info_label)

        self.count_label = QtWidgets.QLabel("Running: 0 | True: 0.0")
        self.count_label.setFont(QtGui.QFont("Arial", 10))
        layout.addWidget(self.count_label)

        self.new_shoe_button = QtWidgets.QPushButton("New Shoe")
        self.new_shoe_button.clicked.connect(self.reset_count)
        layout.addWidget(self.new_shoe_button)

        self.setLayout(layout)

    def update_display(self, bet_size, decision, running, true):
        """Update the overlay with current game information."""
        self.info_label.setText(f"Bet: ${bet_size} | Decision: {decision}")
        self.count_label.setText(f"Running: {running} | True: {true:.1f}")

    def reset_count(self):
        """Reset counts for a new shoe."""
        global running_count, true_count, decks_remaining
        running_count = 0
        true_count = 0
        decks_remaining = 4.0
        self.update_display(10, "Waiting", 0, 0.0)

def get_play_decision(player_total, has_ace, dealer_card, tc):
    """Determine the best playing decision based on basic strategy."""
    # Convert dealer card to numeric value
    if dealer_card in ['K', 'Q', 'J', '10']:
        dealer_value = 10
    elif dealer_card == 'A':
        dealer_value = 11
    else:
        dealer_value = int(dealer_card)

    # Soft hand (has ace counted as 11)
    if has_ace and player_total <= 21:
        if player_total == 21:
            return "Stand"
        if player_total == 20:
            return "Stand"
        if player_total == 19:
            if dealer_value == 6 and tc > 0:
                return "Double Down"
            return "Stand"
        if player_total == 18:
            if dealer_value in [2, 3, 4, 5, 6]:
                return "Double Down" if tc > 0 else "Stand"
            if dealer_value in [7, 8]:
                return "Stand"
            return "Hit"
        if player_total == 17:
            if dealer_value in [3, 4, 5, 6] and tc > 0:
                return "Double Down"
            return "Hit"
        return "Hit"

    # Hard hand (no ace or ace counted as 1)
    if player_total >= 17:
        return "Stand"
    if player_total <= 11:
        return "Hit"
    if player_total == 16:
        if dealer_value in [2, 3, 4, 5, 6]:
            return "Stand"
        return "Hit"
    if player_total == 15:
        if dealer_value in [2, 3, 4, 5, 6]:
            return "Stand"
        return "Hit"
    if player_total == 12:
        if dealer_value in [4, 5, 6]:
            return "Stand"
        return "Hit"
    if player_total in [13, 14]:
        if dealer_value in [2, 3, 4, 5, 6]:
            return "Stand"
        return "Hit"
    return "Hit"

def run_bot():
    """Main function to run the bot."""
    app = QtWidgets.QApplication(sys.argv)
    bot = BlackjackBot()
    overlay = BlackjackOverlay(bot)
    overlay.show()

    # Game loop
    while True:
        try:
            # Detect player's hand and dealer's upcard
            player_cards = bot.detect_hand(bot.player_hand_roi)
            dealer_card = bot.detect_hand(bot.dealer_card_roi)

            if player_cards and dealer_card:
                # Calculate player's hand value
                player_total, has_ace = bot.calculate_hand_value(player_cards)
                dealer_card = dealer_card[0]  # Take the first detected card as dealer's upcard

                # Update counts with all detected cards
                all_detected_cards = player_cards + [dealer_card]
                bot.update_count(all_detected_cards)

                # Get betting and playing decisions
                bet_size = bot.get_bet_size(true_count)
                decision = get_play_decision(player_total, has_ace, dealer_card, true_count)

                # Update the overlay
                overlay.update_display(bet_size, decision, running_count, true_count)
            else:
                overlay.update_display(10, "Waiting", running_count, true_count)

            app.processEvents()
            time.sleep(0.5)  # Check every 0.5 seconds
            
        except KeyboardInterrupt:
            print("Bot stopped by user")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(1)

if __name__ == "__main__":
    # Verify required dependencies and set Tesseract path
    try:
        # Set Tesseract path (adjust for your system)
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Windows
        # For MacOS/Linux, uncomment and adjust:
        # pytesseract.pytesseract.tesseract_cmd = '/usr/local/bin/tesseract'
        run_bot()
    except Exception as e:
        print(f"Startup error: {e}. Please ensure all dependencies are installed.")
