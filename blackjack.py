#blackjack single person game
from random import shuffle

NUM_DECKS = 6
CARD_VALUES = {
    2,3,4,5,6,7,8,9,10,"Jack","Queen","King","Ace"
}
SUITS = {
    "Hearts", "Spades", "Diamonds", "Clubs"
}

class Card():
    def __init__(self, suit, name):
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
    def __init__(self, quantity):
        self.card_order = []
        self.generate_deck(quantity)

    def generate_deck(self, quantity):
        for _ in range(quantity):
            for suit in SUITS:
                for card in CARD_VALUES:
                    self.card_order.append(Card(suit, card))
        self.shuffle_it()
    
    def shuffle_it(self):
        shuffle(self.card_order)

    @property
    def draw_card(self):
        card = self.card_order.pop(0)
        self.card_order.append(card)
        return card


play_deck = Deck(NUM_DECKS)
game_loop = True

def start_hand():
    #bet, one player, one dealer face up, one player, one dealer face down
    player_cards.append(play_deck.draw_card)
    dealer_cards.append(play_deck.draw_card) #face up
    player_cards.append(play_deck.draw_card)
    dealer_cards.append(play_deck.draw_card) #face down

def hit():
    card = play_deck.draw_card
    player_cards.append(card)
    print(f"You drew the {card}")

def double_down():
    hit()
    able_to_hit = False

def stand():
    pass

def check_card_values(hand: list):
    total = 0
    ace = False
    for card in hand:
        if card.alt_value is not None:
            ace = True
        total += card.value
    if total > 21 and ace:
        total = 0
        for card in hand:
            if card.alt_value is not None:
                total += card.alt_value
            else:
                total += card.value
    return total
        
        


while game_loop:
    player_cards = []
    dealer_cards = []
    able_to_hit = True
    start_hand()
    print(f"You get dealt the {player_cards[0]} and the {player_cards[1]}")
    print(f"The dealer is showing the {dealer_cards[0]}")
    print("What do you want to do?")
    need_answer = True
    while need_answer:
        x = input('h for hit, s for stand, d for double down, and q for quit')
        if x not in {'h', 's', 'd', 'q'}:
            print('Invalid input')
        elif x == 'h':
            hit()
            need_answer = False
        elif x == 's':
            stand()
            need_answer = False
        elif x == 'd':
            double_down()
            need_answer = False
        elif x == 'q':
            print('Thanks for playing.')
            need_answer = False
            game_loop = False
    
        