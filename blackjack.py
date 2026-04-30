#blackjack single person game
from random import shuffle

CARD_VALUES = {
    2,3,4,5,6,7,8,9,10,"Jack","Queen","King","Ace"
}
SUITS = {
    "Hearts", "Spades", "Diamonds", "Clubs"
}
class Card():
    def __init__(self, suit: str, name: int | str):
        self.suit = suit
        self.name = name
        self.alt_value = None
        self.face_card = True if type(self.name) == str else False
        if self.face_card:
            if self.name == "Ace":
                self.value = 1
                self.alt_value = 11
            else:
                self.value = 10
        else:
            self.value = int(self.name)

        
    
    def __repr__(self):
        return f"This is the {self.name} of {self.suit}"

    def __str__(self):
        return f"{self.name} of {self.suit}"

class Deck():
    def __init__(self, quantity: int):
        self.card_order = self.generate_deck(quantity)

    def generate_deck(quantity: int):
        for _ in range(quantity):
            for suit in SUITS:
                for card in CARD_VALUES:
                    self.card_order.append(Card(suit, card))
        self.shuffle_it()
    
    def shuffle_it(self):
        shuffle(self.card_order)

    def draw_card(self):
        card = self.card_order.pop(0)
        self.card_order.append(card)
        return card