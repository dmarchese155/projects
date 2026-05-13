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
    Download any "Standard" monthly file. January 2013 is only ~5 MB compressed
    and good for testing. Recent months are 20-35 GB compressed.
"""

import sys
import re
import io
import json
import argparse
import time
from datetime import datetime
from collections import defaultdict
from pathlib import Path

try:
    import zstandard as zstd
except ImportError:
    sys.exit("Missing dependency: pip install zstandard")

try:
    import pandas as pd
except ImportError:
    sys.exit("Missing dependency: pip install pandas")

try:
    import chess
    HAS_CHESS = True
except ImportError:
    print("Warning: python-chess not installed. UCI moves will be omitted.")
    print("         pip install chess")
    HAS_CHESS = False

# ── ECO lookup table ───────────────────────────────────────────────────────
ECO_TABLE = [
    ("f4",                                          "A02", "Bird's Opening"),
    ("f4 d5",                                       "A03", "Bird's Opening: Dutch Variation"),
    ("Nf3",                                         "A04", "Réti Opening"),
    ("Nf3 Nf6",                                     "A05", "Réti Opening"),
    ("c4",                                          "A10", "English Opening"),
    ("c4 e5",                                       "A20", "English Opening: King's English"),
    ("c4 c5",                                       "A30", "English Opening: Symmetrical"),
    ("d4 Nf6 c4 e6",                                "A40", "Queen's Pawn Game"),
    ("d4 Nf6 c4 c5 d5 b5",                          "A57", "Benko Gambit"),
    ("d4 Nf6 c4 g6",                                "A60", "Benoni Defense"),
    ("d4 f5",                                       "A80", "Dutch Defense"),
    ("e4 c6",                                       "B10", "Caro-Kann Defense"),
    ("e4 c6 d4 d5 e5",                              "B12", "Caro-Kann: Advance Variation"),
    ("e4 c6 d4 d5 Nc3",                             "B13", "Caro-Kann: Exchange Variation"),
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
    ("d4 d5",                                       "D00", "Queen's Pawn Game"),
    ("d4 d5 Nf3",                                   "D02", "London System"),
    ("d4 d5 c4",                                    "D06", "Queen's Gambit"),
    ("d4 d5 c4 e6",                                 "D30", "Queen's Gambit Declined"),
    ("d4 d5 c4 c6",                                 "D10", "Slav Defense"),
    ("d4 d5 c4 c6 Nc3 Nf6",                         "D43", "Semi-Slav Defense"),
    ("d4 d5 c4 dxc4",                               "D20", "Queen's Gambit Accepted"),
    ("d4 Nf6",                                      "A45", "Indian Defense"),
    ("d4 Nf6 c4",                                   "E00", "Queen's Indian / Nimzo"),
    ("d4 Nf6 c4 e6",                                "E00", "Queen's Indian"),
    ("d4 Nf6 c4 e6 Nc3 Bb4",                        "E20", "Nimzo-Indian Defense"),
    ("d4 Nf6 c4 g6 Nc3 d5",                         "D80", "Grünfeld Defense"),
    ("d4 Nf6 c4 g6",                                "E60", "King's Indian Defense"),
    ("d4 Nf6 c4 e6 g3",                             "E00", "Catalan Opening"),
]
ECO_TABLE.sort(key=lambda x: len(x[0]), reverse=True)


def lookup_eco(move_string: str):
    for prefix, eco, name in ECO_TABLE:
        if move_string.startswith(prefix):
            return eco, name
    return None, None


# ── Move parsing ───────────────────────────────────────────────────────────
# Strip comments, clocks, move numbers, result tokens — leave only SAN moves
_STRIP = re.compile(r'\{[^}]*\}|\([^)]*\)|\$\d+|[10½]-[10½]|1/2-1/2|\*|\d+\.+')

def parse_moves(moves_line: str, n: int = 10) -> list:
    cleaned = _STRIP.sub(' ', moves_line)
    tokens  = cleaned.split()
    # Keep only valid SAN tokens (start with a letter, not a result string)
    moves = [t for t in tokens if t and t[0].isalpha() and t not in ('O-O-O', 'O-O') or
             t in ('O-O-O', 'O-O')]
    # Re-filter: valid SAN starts with a-h (pawn), N,B,R,Q,K (piece), or O (castling)
    moves = [t for t in tokens if t and (t[0] in 'abcdefghNBRQKO')]
    return moves[:n]


# ── SAN → UCI ──────────────────────────────────────────────────────────────
def san_to_uci(san_list: list) -> list:
    if not HAS_CHESS or not san_list:
        return []
    try:
        board = chess.Board()
        out   = []
        for san in san_list:
            move = board.parse_san(san)
            out.append(move.uci())
            board.push(move)
        return out
    except Exception:
        return []


# ── Header helpers ─────────────────────────────────────────────────────────
_HDR = re.compile(r'^\[(\w+)\s+"([^"]*)"\]')

def parse_header(line: str):
    m = _HDR.match(line)
    return (m.group(1), m.group(2)) if m else (None, None)

def parse_result(r: str):
    return {'1-0': 'white', '0-1': 'black', '1/2-1/2': 'draw'}.get(r)

def parse_elo(s: str):
    try:
        v = int(s)
        return v if 100 < v < 4000 else None
    except (ValueError, TypeError):
        return None

def parse_tc(tc: str):
    if not tc or tc == '-':
        return 'unknown'
    try:
        base = int(tc.split('+')[0])
        if base < 30:    return 'ultrabullet'
        if base < 180:   return 'bullet'
        if base < 600:   return 'blitz'
        if base < 1800:  return 'rapid'
        return 'classical'
    except (ValueError, IndexError):
        return 'unknown'


# ── Core streaming parser ──────────────────────────────────────────────────
#
# KEY FIX: use io.TextIOWrapper around the zstd stream so we can iterate
# line-by-line with a simple `for line in reader` — no manual buffer splitting,
# no growing byte strings, no state machine bugs.
#
# Lichess PGN block structure (one game):
#   [Tag1 "value"]
#   [Tag2 "value"]
#   ...            ← one or more blank lines separate headers from moves
#   1. e4 e5 ...   ← moves on a single line
#                  ← blank line ends the game block
#
def stream_games(zst_path: str, min_elo=None, max_elo=None, limit=None):
    dctx   = zstd.ZstdDecompressor()
    n_seen = 0

    with open(zst_path, 'rb') as fh:
        # stream_reader → binary stream; wrap in TextIOWrapper for text iteration
        raw    = dctx.stream_reader(fh, read_size=1 << 16)
        reader = io.TextIOWrapper(raw, encoding='utf-8', errors='replace')

        headers    = {}
        moves_line = None

        for raw_line in reader:
            line = raw_line.strip()

            if line.startswith('['):
                # Header tag
                key, val = parse_header(line)
                if key:
                    headers[key] = val
                # If we somehow have a leftover moves_line from previous game, emit it
                # (handles files without trailing blank line between games)
                if moves_line is not None:
                    game = _build_game(headers, moves_line, min_elo, max_elo)
                    if game:
                        yield game
                        n_seen += 1
                        if limit and n_seen >= limit:
                            return
                    moves_line = None
                    headers    = {}
                    key, val   = parse_header(line)
                    if key:
                        headers[key] = val

            elif line == '':
                # Blank line: if we have a moves line buffered, this ends the game
                if moves_line is not None and headers:
                    game = _build_game(headers, moves_line, min_elo, max_elo)
                    if game:
                        yield game
                        n_seen += 1
                        if limit and n_seen >= limit:
                            return
                    headers    = {}
                    moves_line = None

            else:
                # Non-empty, non-header line = moves
                # (Lichess puts all moves on one line)
                moves_line = line

        # Flush the very last game if file doesn't end with a blank line
        if moves_line is not None and headers:
            game = _build_game(headers, moves_line, min_elo, max_elo)
            if game:
                yield game


def _build_game(headers: dict, moves_line: str, min_elo, max_elo):
    we = parse_elo(headers.get('WhiteElo'))
    be = parse_elo(headers.get('BlackElo'))

    if min_elo is not None and (not we or we < min_elo or not be or be < min_elo):
        return None
    if max_elo is not None and (not we or we > max_elo or not be or be > max_elo):
        return None

    moves = parse_moves(moves_line, n=50)
    if not moves:
        return None

    return {
        'moves':        moves[:10],
        'total_moves':  len(moves),
        'result':       parse_result(headers.get('Result', '*')),
        'white_elo':    we,
        'black_elo':    be,
        'time_control': parse_tc(headers.get('TimeControl', '-')),
    }


# ── Accumulator ────────────────────────────────────────────────────────────
class Acc:
    def __init__(self):
        self.counts          = defaultdict(int)
        self.white_wins      = defaultdict(int)
        self.draws           = defaultdict(int)
        self.black_wins      = defaultdict(int)
        self.elo_w_sum       = defaultdict(int)
        self.elo_b_sum       = defaultdict(int)
        self.elo_n           = defaultdict(int)
        self.moves_sum       = defaultdict(int)
        self.tc              = defaultdict(lambda: defaultdict(int))
        self.total           = 0
        self.with_moves      = 0

    def add(self, g: dict):
        self.total += 1
        if not g['moves']:
            return
        self.with_moves += 1
        key = ' '.join(g['moves'])
        self.counts[key]     += 1
        r = g['result']
        if r == 'white': self.white_wins[key] += 1
        elif r == 'draw': self.draws[key]     += 1
        elif r == 'black': self.black_wins[key] += 1
        we, be = g['white_elo'], g['black_elo']
        if we and be:
            self.elo_w_sum[key] += we
            self.elo_b_sum[key] += be
            self.elo_n[key]     += 1
        self.moves_sum[key]  += g['total_moves']
        self.tc[key][g['time_control']] += 1

    def top_n(self, n: int) -> list:
        top  = sorted(self.counts, key=lambda k: self.counts[k], reverse=True)[:n]
        total = self.total or 1
        out  = []
        for rank, key in enumerate(top, 1):
            san   = key.split()
            uci   = san_to_uci(san)
            gc    = self.counts[key]
            ww    = self.white_wins[key]
            dd    = self.draws[key]
            bw    = self.black_wins[key]
            dec   = ww + dd + bw or 1
            en    = self.elo_n[key]
            eco, name = lookup_eco(' '.join(san))
            out.append({
                'rank':             rank,
                'moves_san':        san,
                'moves_uci':        uci or None,
                'move_string':      key,
                'game_count':       gc,
                'pct_of_total':     round(gc / total * 100, 4),
                'white_wins':       ww,
                'draws':            dd,
                'black_wins':       bw,
                'white_win_pct':    round(ww / dec * 100, 1),
                'draw_pct':         round(dd / dec * 100, 1),
                'black_win_pct':    round(bw / dec * 100, 1),
                'avg_white_elo':    round(self.elo_w_sum[key] / en) if en else None,
                'avg_black_elo':    round(self.elo_b_sum[key] / en) if en else None,
                'avg_game_length':  round(self.moves_sum[key] / gc) if gc else None,
                'time_controls':    dict(self.tc[key]),
                'eco_guess':        eco,
                'opening_name':     name,
            })
        return out


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description='Parse Lichess .pgn.zst → top-N openings JSON')
    ap.add_argument('file',      help='Path to .pgn.zst file')
    ap.add_argument('--top',     type=int, default=500,  help='Number of openings (default 500)')
    ap.add_argument('--out',     type=str, default=None, help='Output JSON path')
    ap.add_argument('--min-elo', type=int, default=None, help='Min ELO filter')
    ap.add_argument('--max-elo', type=int, default=None, help='Max ELO filter')
    ap.add_argument('--limit',   type=int, default=None, help='Stop after N games (for testing)')
    ap.add_argument('--report-every', type=int, default=100_000, help='Progress interval')
    args = ap.parse_args()

    in_path  = Path(args.file)
    if not in_path.exists():
        sys.exit(f'File not found: {in_path}')

    out_path = Path(args.out) if args.out else \
               in_path.parent / (in_path.stem.replace('.pgn','') + '_openings.json')

    print(f'Input  : {in_path}  ({in_path.stat().st_size / 1e6:.1f} MB compressed)')
    print(f'Output : {out_path}')
    print(f'Top N  : {args.top}')
    if args.min_elo: print(f'Min ELO: {args.min_elo}')
    if args.max_elo: print(f'Max ELO: {args.max_elo}')
    if args.limit:   print(f'Limit  : {args.limit:,} games')
    print()

    acc = Acc()
    t0  = time.time()

    for i, game in enumerate(stream_games(in_path, args.min_elo, args.max_elo, args.limit), 1):
        acc.add(game)
        if i % args.report_every == 0:
            el   = time.time() - t0
            rate = i / el
            print(f'  {i:>10,} games  |  {rate:>8,.0f} games/sec  |  '
                  f'{el:>6.1f}s  |  {len(acc.counts):,} unique openings')

    el = time.time() - t0
    print(f'\nDone.  {acc.total:,} games in {el:.1f}s  ({acc.total/el:,.0f} games/sec)')
    print(f'Games with moves : {acc.with_moves:,}')
    print(f'Unique openings  : {len(acc.counts):,}')
    print(f'Building top {args.top}...')

    top = acc.top_n(args.top)

    output = {
        'meta': {
            'source_file':           in_path.name,
            'total_games_processed': acc.total,
            'games_with_moves':      acc.with_moves,
            'unique_openings_found': len(acc.counts),
            'top_n':                 args.top,
            'min_elo_filter':        args.min_elo,
            'max_elo_filter':        args.max_elo,
            'generated_at':          datetime.utcnow().isoformat(),
            'processing_time_sec':   round(el, 1),
        },
        'openings': top,
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f'\nSaved → {out_path}  ({out_path.stat().st_size / 1024:.1f} KB)')
    print(f'\nTop 20 openings:')
    print(f'{"Rank":>4}  {"Games":>8}  {"%":>6}  {"W%":>5} {"D%":>5} {"B%":>5}  Opening')
    print('─' * 72)
    for o in top[:20]:
        name = o['opening_name'] or o['move_string'][:38]
        print(f'{o["rank"]:>4}  {o["game_count"]:>8,}  '
              f'{o["pct_of_total"]:>5.2f}%  '
              f'{o["white_win_pct"]:>4.1f} '
              f'{o["draw_pct"]:>4.1f} '
              f'{o["black_win_pct"]:>4.1f}  '
              f'{name}')

if __name__ == '__main__':
    main()