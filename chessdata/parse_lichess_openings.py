"""
parse_lichess_openings.py
─────────────────────────────────────────────────────────────────────────────
Reads a Lichess monthly .pgn.zst file, extracts the first 5 moves of every
game, groups by move sequence, and outputs the top N openings as a rich JSON
file ready to feed directly into the chess visualiser.

USAGE
─────
    python parse_lichess_openings.py <file.pgn.zst> [options]

    python parse_lichess_openings.py lichess_db_standard_rated_2024-01.pgn.zst
    python parse_lichess_openings.py lichess_db_standard_rated_2024-01.pgn.zst --top 500
    python parse_lichess_openings.py lichess_db_standard_rated_2024-01.pgn.zst --top 500 --out openings.json
    python parse_lichess_openings.py lichess_db_standard_rated_2024-01.pgn.zst --min-elo 1500 --max-elo 2200

INSTALL DEPENDENCIES
────────────────────
    pip install zstandard pandas chess tqdm

WHERE TO GET THE DATA FILE
──────────────────────────
    https://database.lichess.org/
    Download any "Standard" monthly file, e.g.:
    https://database.lichess.org/standard/lichess_db_standard_rated_2024-01.pgn.zst
    Warning: files are large (compressed ~20–35 GB for recent months).
    For testing, January 2013 is only ~5 MB compressed.

OUTPUT FORMAT (openings.json)
─────────────────────────────
    {
      "meta": {
        "source_file": "lichess_db_standard_rated_2024-01.pgn.zst",
        "total_games_processed": 12345678,
        "games_with_5_moves": 11234567,
        "top_n": 500,
        "generated_at": "2024-05-12T10:30:00"
      },
      "openings": [
        {
          "rank": 1,
          "moves_san": ["e4", "e5", "Nf3", "Nc6", "Bc4"],   ← Standard Algebraic Notation
          "moves_uci": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"],  ← UCI (for the visualiser)
          "move_string": "e4 e5 Nf3 Nc6 Bc4",               ← flat string for grouping/display
          "game_count": 458231,                              ← how many games had this exact opening
          "pct_of_total": 3.74,                              ← % of all games processed
          "white_wins": 189432,                              ← raw counts
          "draws": 98234,
          "black_wins": 170565,
          "white_win_pct": 41.3,                             ← percentages (useful for display)
          "draw_pct": 21.4,
          "black_win_pct": 37.2,
          "avg_white_elo": 1542,                             ← average player ratings
          "avg_black_elo": 1538,
          "avg_game_length": 34,                             ← average total moves in games with this opening
          "time_controls": {                                 ← breakdown by time control
            "bullet": 123400,
            "blitz": 210000,
            "rapid": 89000,
            "classical": 35831
          },
          "eco_guess": "C50",                                ← ECO code if detectable (best-effort)
          "opening_name": "Italian Game"                     ← name if detectable (best-effort)
        },
        ...
      ]
    }
"""

import sys
import re
import json
import argparse
import time
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# ── optional progress bar ──────────────────────────────────────────────────
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# ── required libraries ─────────────────────────────────────────────────────
try:
    import zstandard as zstd
except ImportError:
    sys.exit("Missing: pip install zstandard")

try:
    import pandas as pd
except ImportError:
    sys.exit("Missing: pip install pandas")

try:
    import chess
    import chess.pgn
    HAS_CHESS = True
except ImportError:
    # chess library is used for:
    #   - converting SAN moves to UCI
    #   - detecting ECO codes / opening names
    # The script still works without it but UCI moves won't be computed.
    print("Warning: python-chess not installed. UCI moves will be omitted.")
    print("         Install with: pip install chess")
    HAS_CHESS = False

# ── ECO lookup table (abridged – covers the most common openings) ──────────
# Full table: https://github.com/lichess-org/chess-openings
# Format: (move_string_prefix, eco, name)
# We match on the start of the move_string so longer sequences take priority.
ECO_TABLE = [
    # A – Flank openings
    ("f4",                                          "A02", "Bird's Opening"),
    ("f4 d5",                                       "A03", "Bird's Opening: Dutch Variation"),
    ("Nf3",                                         "A04", "Réti Opening"),
    ("Nf3 Nf6",                                     "A05", "Réti Opening"),
    ("c4",                                          "A10", "English Opening"),
    ("c4 e5",                                       "A20", "English Opening: King's English"),
    ("c4 c5",                                       "A30", "English Opening: Symmetrical"),
    ("d4 Nf6 c4 e6",                                "A40", "Queen's Pawn Game"),
    ("d4 Nf6 c4 g6",                                "A60", "Benoni Defense"),
    ("d4 Nf6 c4 c5 d5 b5",                          "A57", "Benko Gambit"),
    ("d4 f5",                                       "A80", "Dutch Defense"),
    # B – Semi-open games
    ("e4 c6",                                       "B10", "Caro-Kann Defense"),
    ("e4 c6 d4 d5 Nc3",                             "B13", "Caro-Kann: Exchange Variation"),
    ("e4 c6 d4 d5 e5",                              "B12", "Caro-Kann: Advance Variation"),
    ("e4 d5",                                       "B01", "Scandinavian Defense"),
    ("e4 d5 exd5 Qxd5",                             "B01", "Scandinavian: Main Line"),
    ("e4 Nf6",                                      "B02", "Alekhine's Defense"),
    ("e4 g6",                                       "B06", "Modern Defense"),
    ("e4 d6",                                       "B07", "Pirc Defense"),
    ("e4 c5",                                       "B20", "Sicilian Defense"),
    ("e4 c5 Nf3",                                   "B23", "Sicilian: Open"),
    ("e4 c5 Nf3 Nc6",                               "B23", "Sicilian: Open, Nc6"),
    ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6",       "B90", "Sicilian: Najdorf"),
    ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6",       "B70", "Sicilian: Dragon"),
    ("e4 e6",                                       "C00", "French Defense"),
    ("e4 e6 d4 d5 e5",                              "C02", "French: Advance"),
    ("e4 e6 d4 d5 exd5",                            "C01", "French: Exchange"),
    ("e4 e6 d4 d5 Nc3",                             "C10", "French: Classical"),
    # C – Open games
    ("e4 e5",                                       "C20", "Open Game"),
    ("e4 e5 f4",                                    "C30", "King's Gambit"),
    ("e4 e5 Nf3",                                   "C40", "King's Knight Opening"),
    ("e4 e5 Nf3 Nf6",                               "C42", "Petrov's Defense"),
    ("e4 e5 Nf3 Nc6",                               "C44", "Open Game"),
    ("e4 e5 Nf3 Nc6 Bc4",                           "C50", "Italian Game"),
    ("e4 e5 Nf3 Nc6 Bc4 Bc5",                       "C53", "Italian: Giuoco Piano"),
    ("e4 e5 Nf3 Nc6 Bc4 Nf6",                       "C55", "Two Knights Defense"),
    ("e4 e5 Nf3 Nc6 Bb5",                           "C60", "Ruy López"),
    ("e4 e5 Nf3 Nc6 d4",                            "C45", "Scotch Game"),
    ("e4 e5 Nf3 Nc6 d4 exd4",                       "C45", "Scotch: Main Line"),
    ("e4 e5 Nf3 Nc6 Nc3",                           "C46", "Three Knights / Vienna"),
    ("e4 e5 Nf3 Nc6 Nc3 Nf6",                       "C46", "Four Knights Game"),
    ("e4 e5 Bc4",                                   "C23", "Bishop's Opening"),
    ("e4 e5 Nc3",                                   "C25", "Vienna Game"),
    # D – Closed games
    ("d4 d5",                                       "D00", "Queen's Pawn Game"),
    ("d4 d5 Nf3",                                   "D02", "London System"),
    ("d4 d5 c4",                                    "D06", "Queen's Gambit"),
    ("d4 d5 c4 e6",                                 "D30", "Queen's Gambit Declined"),
    ("d4 d5 c4 c6",                                 "D10", "Slav Defense"),
    ("d4 d5 c4 c6 Nc3 Nf6",                         "D43", "Semi-Slav Defense"),
    ("d4 d5 c4 dxc4",                               "D20", "Queen's Gambit Accepted"),
    # E – Indian systems
    ("d4 Nf6",                                      "A45", "Indian Defense"),
    ("d4 Nf6 c4",                                   "E00", "Queen's Indian / Nimzo"),
    ("d4 Nf6 c4 e6",                                "E00", "Queen's Indian"),
    ("d4 Nf6 c4 e6 Nc3 Bb4",                        "E20", "Nimzo-Indian Defense"),
    ("d4 Nf6 c4 g6",                                "E60", "King's Indian Defense"),
    ("d4 Nf6 c4 g6 Nc3 d5",                         "D80", "Grünfeld Defense"),
    ("d4 Nf6 c4 e6 g3",                             "E00", "Catalan Opening"),
]
# Sort longest-first so we match the most specific opening
ECO_TABLE.sort(key=lambda x: len(x[0]), reverse=True)


def lookup_eco(move_string: str):
    """Return (eco, name) for the best matching ECO prefix, or (None, None)."""
    for prefix, eco, name in ECO_TABLE:
        if move_string.startswith(prefix):
            return eco, name
    return None, None


# ── SAN → UCI conversion using python-chess ───────────────────────────────

def san_moves_to_uci(san_list: list[str]) -> list[str]:
    """Convert a list of SAN move strings to UCI strings.
    Returns empty list on any error (malformed game, etc.)."""
    if not HAS_CHESS:
        return []
    try:
        board = chess.Board()
        uci_moves = []
        for san in san_list:
            move = board.parse_san(san)
            uci_moves.append(move.uci())
            board.push(move)
        return uci_moves
    except Exception:
        return []


# ── PGN move string parsing ────────────────────────────────────────────────

# Moves line looks like: "1. e4 e5 2. Nf3 Nc6 3. Bc4 { [%eval 0.17] } *"
# We want: ["e4", "e5", "Nf3", "Nc6", "Bc4"]
_MOVE_NUMBER = re.compile(r'\d+\.+')
_ANNOTATION  = re.compile(r'\{[^}]*\}')   # strip {comments}
_CLOCK       = re.compile(r'\[%[^\]]+\]') # strip [%clk ...]
_RESULT      = re.compile(r'(1-0|0-1|1/2-1/2|\*)\s*$')
_WHITESPACE  = re.compile(r'\s+')


def parse_moves(moves_line: str, n: int = 10) -> list[str]:
    """Extract the first n half-moves (plies) from a PGN moves line.
    Returns SAN tokens like ['e4','e5','Nf3','Nc6','Bc4',...].
    """
    s = moves_line
    s = _ANNOTATION.sub('', s)
    s = _CLOCK.sub('', s)
    s = _RESULT.sub('', s)
    s = _MOVE_NUMBER.sub('', s)
    tokens = _WHITESPACE.sub(' ', s).strip().split()
    # Filter out any leftover punctuation-only tokens
    tokens = [t for t in tokens if re.match(r'^[a-zA-Z][^\s]*$', t)]
    return tokens[:n]


# ── Header parsing ─────────────────────────────────────────────────────────

_HEADER = re.compile(r'^\[(\w+)\s+"([^"]*)"\]$')


def parse_header(line: str):
    """Return (key, value) from a PGN header line, or (None, None)."""
    m = _HEADER.match(line.strip())
    if m:
        return m.group(1), m.group(2)
    return None, None


def parse_result(result_str: str):
    """Return ('white','draw','black',None) from a PGN Result tag."""
    if result_str == '1-0':   return 'white'
    if result_str == '0-1':   return 'black'
    if result_str == '1/2-1/2': return 'draw'
    return None


def parse_elo(elo_str: str):
    """Return int ELO or None."""
    try:
        v = int(elo_str)
        return v if 100 < v < 4000 else None
    except (ValueError, TypeError):
        return None


def parse_time_control(tc: str):
    """Map a Lichess TimeControl string to a category."""
    if not tc or tc == '-':
        return 'unknown'
    try:
        base = int(tc.split('+')[0])
        if base < 30:       return 'ultrabullet'
        if base < 180:      return 'bullet'
        if base < 600:      return 'blitz'
        if base < 1800:     return 'rapid'
        return 'classical'
    except (ValueError, IndexError):
        return 'unknown'


# ── Stream parser ──────────────────────────────────────────────────────────

def stream_games(zst_path: str, min_elo: int = None, max_elo: int = None,
                 limit: int = None):
    """
    Lazily stream games from a .pgn.zst file.
    Yields dicts with keys: moves, result, white_elo, black_elo,
                             time_control, total_moves
    Uses a simple state-machine parser (no external chess library needed
    for the streaming step) — same approach as the Spark pipeline but
    without Spark.
    """
    dctx = zstd.ZstdDecompressor()

    headers = {}
    moves_line = None
    in_moves = False
    games_yielded = 0

    with open(zst_path, 'rb') as fh:
        stream = dctx.stream_reader(fh)
        buf = b''

        while True:
            chunk = stream.read(1 << 20)  # 1 MB at a time
            if not chunk:
                break
            buf += chunk

            # Process complete lines
            while b'\n' in buf:
                line_bytes, buf = buf.split(b'\n', 1)
                try:
                    line = line_bytes.decode('utf-8', errors='replace').strip()
                except Exception:
                    continue

                if not line:
                    # Blank line: if we were collecting headers, next non-blank
                    # line is the moves line
                    if headers and not in_moves:
                        in_moves = True
                    elif in_moves and moves_line is not None:
                        # End of game block — emit
                        game = _emit_game(headers, moves_line,
                                          min_elo, max_elo)
                        if game is not None:
                            yield game
                            games_yielded += 1
                            if limit and games_yielded >= limit:
                                return
                        headers = {}
                        moves_line = None
                        in_moves = False
                    continue

                if line.startswith('['):
                    key, val = parse_header(line)
                    if key:
                        headers[key] = val
                    in_moves = False
                elif in_moves:
                    moves_line = line
                    in_moves = False  # will be emitted on next blank line

        # Flush last game if file doesn't end with blank line
        if headers and moves_line is not None:
            game = _emit_game(headers, moves_line, min_elo, max_elo)
            if game is not None:
                yield game


def _emit_game(headers: dict, moves_line: str,
               min_elo: int, max_elo: int):
    """Parse a completed game block. Returns dict or None if filtered out."""
    white_elo = parse_elo(headers.get('WhiteElo'))
    black_elo = parse_elo(headers.get('BlackElo'))

    # ELO filter
    if min_elo is not None:
        if (white_elo is None or white_elo < min_elo or
                black_elo is None or black_elo < min_elo):
            return None
    if max_elo is not None:
        if (white_elo is None or white_elo > max_elo or
                black_elo is None or black_elo > max_elo):
            return None

    # Parse moves — we want first 10 half-moves (= 5 full moves)
    all_moves = parse_moves(moves_line, n=50)
    if len(all_moves) < 1:
        return None

    total_moves = len(all_moves)
    first_5_moves = all_moves[:10]   # up to 10 half-moves

    return {
        'moves':        first_5_moves,
        'total_moves':  total_moves,
        'result':       parse_result(headers.get('Result', '*')),
        'white_elo':    white_elo,
        'black_elo':    black_elo,
        'time_control': parse_time_control(headers.get('TimeControl', '-')),
    }


# ── Aggregation ────────────────────────────────────────────────────────────

class OpeningAccumulator:
    """Accumulates per-opening statistics without storing all games in memory."""

    def __init__(self):
        self.counts         = defaultdict(int)
        self.white_wins     = defaultdict(int)
        self.draws          = defaultdict(int)
        self.black_wins     = defaultdict(int)
        self.white_elo_sum  = defaultdict(int)
        self.black_elo_sum  = defaultdict(int)
        self.elo_count      = defaultdict(int)
        self.total_moves_sum= defaultdict(int)
        self.tc_counts      = defaultdict(lambda: defaultdict(int))
        self.total_games    = 0
        self.games_with_moves = 0

    def add(self, game: dict):
        self.total_games += 1
        moves = game['moves']
        if not moves:
            return
        self.games_with_moves += 1

        key = ' '.join(moves)  # e.g. "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d4 exd4"

        self.counts[key] += 1

        result = game['result']
        if result == 'white': self.white_wins[key] += 1
        elif result == 'draw': self.draws[key] += 1
        elif result == 'black': self.black_wins[key] += 1

        we = game['white_elo']
        be = game['black_elo']
        if we and be:
            self.white_elo_sum[key] += we
            self.black_elo_sum[key] += be
            self.elo_count[key] += 1

        self.total_moves_sum[key] += game['total_moves']

        tc = game.get('time_control', 'unknown')
        self.tc_counts[key][tc] += 1

    def top_n(self, n: int) -> list[dict]:
        """Return the top-n openings sorted by game count, fully enriched."""
        top_keys = sorted(self.counts, key=lambda k: self.counts[k],
                          reverse=True)[:n]
        results = []
        total = self.total_games or 1

        for rank, key in enumerate(top_keys, start=1):
            san_moves = key.split()
            uci_moves = san_moves_to_uci(san_moves)

            gc = self.counts[key]
            ww = self.white_wins[key]
            dd = self.draws[key]
            bw = self.black_wins[key]
            decided = ww + dd + bw or 1

            ec = self.elo_count[key]
            avg_we = round(self.white_elo_sum[key] / ec) if ec else None
            avg_be = round(self.black_elo_sum[key] / ec) if ec else None
            avg_gl = round(self.total_moves_sum[key] / gc) if gc else None

            eco, name = lookup_eco(' '.join(san_moves))

            results.append({
                'rank':           rank,
                'moves_san':      san_moves,
                'moves_uci':      uci_moves if uci_moves else None,
                'move_string':    key,
                'game_count':     gc,
                'pct_of_total':   round(gc / total * 100, 4),
                'white_wins':     ww,
                'draws':          dd,
                'black_wins':     bw,
                'white_win_pct':  round(ww / decided * 100, 1),
                'draw_pct':       round(dd / decided * 100, 1),
                'black_win_pct':  round(bw / decided * 100, 1),
                'avg_white_elo':  avg_we,
                'avg_black_elo':  avg_be,
                'avg_game_length': avg_gl,
                'time_controls':  dict(self.tc_counts[key]),
                'eco_guess':      eco,
                'opening_name':   name,
            })

        return results


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parse a Lichess .pgn.zst file → top-N openings JSON"
    )
    parser.add_argument('file',
        help='Path to .pgn.zst file (e.g. lichess_db_standard_rated_2024-01.pgn.zst)')
    parser.add_argument('--top', type=int, default=500,
        help='Number of top openings to output (default: 500)')
    parser.add_argument('--out', type=str, default=None,
        help='Output JSON file path (default: <file_stem>_openings.json)')
    parser.add_argument('--min-elo', type=int, default=None,
        help='Minimum ELO for both players (e.g. 1500)')
    parser.add_argument('--max-elo', type=int, default=None,
        help='Maximum ELO for both players (e.g. 2200)')
    parser.add_argument('--limit', type=int, default=None,
        help='Stop after processing this many games (useful for testing)')
    parser.add_argument('--report-every', type=int, default=500_000,
        help='Print progress every N games (default: 500000)')
    args = parser.parse_args()

    in_path = Path(args.file)
    if not in_path.exists():
        sys.exit(f"File not found: {in_path}")

    out_path = Path(args.out) if args.out else \
               in_path.parent / (in_path.stem.replace('.pgn', '') + '_openings.json')

    print(f"Input  : {in_path}")
    print(f"Output : {out_path}")
    print(f"Top N  : {args.top}")
    if args.min_elo: print(f"Min ELO: {args.min_elo}")
    if args.max_elo: print(f"Max ELO: {args.max_elo}")
    if args.limit:   print(f"Limit  : {args.limit:,} games")
    print()

    acc = OpeningAccumulator()
    t0  = time.time()

    game_stream = stream_games(
        str(in_path),
        min_elo=args.min_elo,
        max_elo=args.max_elo,
        limit=args.limit,
    )

    for i, game in enumerate(game_stream, start=1):
        acc.add(game)
        if i % args.report_every == 0:
            elapsed = time.time() - t0
            rate = i / elapsed
            print(f"  {i:>12,} games  |  {rate:,.0f} games/sec  |  "
                  f"{elapsed:.0f}s elapsed  |  "
                  f"{len(acc.counts):,} unique openings so far")

    elapsed = time.time() - t0
    print(f"\nDone. {acc.total_games:,} games in {elapsed:.1f}s "
          f"({acc.total_games/elapsed:,.0f} games/sec)")
    print(f"Games with at least 1 move : {acc.games_with_moves:,}")
    print(f"Unique opening sequences   : {len(acc.counts):,}")
    print(f"Building top {args.top}...")

    top = acc.top_n(args.top)

    output = {
        'meta': {
            'source_file':            in_path.name,
            'total_games_processed':  acc.total_games,
            'games_with_moves':       acc.games_with_moves,
            'unique_openings_found':  len(acc.counts),
            'top_n':                  args.top,
            'min_elo_filter':         args.min_elo,
            'max_elo_filter':         args.max_elo,
            'generated_at':           datetime.utcnow().isoformat(),
            'processing_time_sec':    round(elapsed, 1),
        },
        'openings': top,
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved → {out_path}  ({out_path.stat().st_size / 1024:.1f} KB)")

    # ── Quick summary table ────────────────────────────────────────────────
    print(f"\nTop 20 openings:")
    print(f"{'Rank':>4}  {'Games':>10}  {'%':>6}  {'W%':>5}  {'D%':>5}  {'B%':>5}  Opening")
    print("─" * 80)
    for o in top[:20]:
        name = o['opening_name'] or o['move_string'][:40]
        print(f"{o['rank']:>4}  {o['game_count']:>10,}  "
              f"{o['pct_of_total']:>5.2f}%  "
              f"{o['white_win_pct']:>4.1f}  "
              f"{o['draw_pct']:>4.1f}  "
              f"{o['black_win_pct']:>4.1f}  "
              f"{name}")


if __name__ == '__main__':
    main()
