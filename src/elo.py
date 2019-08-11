import os
import math
import random
import operator
from functools import partial

# 3rd party: https://github.com/google/python-fire
import fire

from ggplib.util import log

from ggpzero.util import attrutil as at
from ggpzero.util import symmetry
from ggpzero.nn import manager

from ggpzero.battle.common import get_player, run, MatchTooLong


NUM_GAMES = 25
MOVE_TIME = 30.0
RESIGN_PCT = -1
STARTING_ELO = 1500.0
MAX_ADD_COUNT = 200

CHOOSE_BUCKETS = [10, 20, 30, 40, 50, 60, 80, 100]


def probability(rating1, rating2):
    return 1.0 * 1.0 / (1 + 1.0 * math.pow(10, 1.0 * (rating1 - rating2) / 400))


def next_elo_rating(rating_a, rating_b, k0, k1, player_a_wins):

    # Winning probability of players
    pa = probability(rating_b, rating_a)
    pb = probability(rating_a, rating_b)

    # When Player A wins
    if player_a_wins:
        new_rating_a = rating_a + k0 * (1.0 - pa)
        new_rating_b = rating_b + k1 * (0.0 - pb)
    else:
        new_rating_a = rating_a + k0 * (0.0 - pa)
        new_rating_b = rating_b + k1 * (1.0 - pb)

    log.info("rating_a k=%s %s -> %s" % (k0, rating_a, new_rating_a))
    log.info("rating_b k=%s %s -> %s" % (k1, rating_b, new_rating_b))
    return new_rating_a, new_rating_b


@at.register_attrs
class PlayerRating(object):
    name = at.attribute("xxyyyzz")
    played = at.attribute(42)
    elo = at.attribute(1302.124)
    fixed = at.attribute(False)


@at.register_attrs
class AllRatings(object):
    game = at.attribute("game")

    # list of PlayerRating
    players = at.attribute(default=at.attr_factory(list))

    # simple log of recent games
    log = at.attribute(default=at.attr_factory(list))


def define_player(game, gen, playouts, version, **extra_opts):
    opts = dict(verbose=True,
                puct_constant=0.85,

                dirichlet_noise_pct=0.5,

                fpu_prior_discount=0.25,
                fpu_prior_discount_root=0.1,

                choose="choose_temperature",
                temperature=1.5,

                depth_temperature_max=10.0,
                depth_temperature_start=2,
                depth_temperature_increment=1.0,
                depth_temperature_stop=2,
                random_scale=0.8,

                max_dump_depth=2,
                top_visits_best_guess_converge_ratio=0.85,

                backup_finalised=True,
                lookup_transpositions=True,

                # Passed in
                playouts_per_iteration=playouts)

    if version == 3:
        opts.update(name="%s_v3" % game,

                    puct_constant_root=0.85,

                    dirichlet_noise_pct=0.33,

                    choose="choose_temperature",
                    temperature=1.0,
                    depth_temperature_max=1.0,
                    depth_temperature_start=2,
                    depth_temperature_increment=0,
                    depth_temperature_stop=2,
                    random_scale=0.99,

                    minimax_backup_ratio=0.75,

                    batch_size=8,

                    think_time=MOVE_TIME,
                    converged_visits=playouts / 2)
        opts.update(extra_opts)
        return get_player("puct", MOVE_TIME, gen, **opts)

    elif version == 2:
        opts.update(name="%s_v2" % game,

                    puct_constant_root=0.85,

                    minimax_backup_ratio=0.75,

                    batch_size=8,

                    think_time=MOVE_TIME,
                    converge_relaxed=playouts / 2)

        opts.update(extra_opts)
        return get_player("puct", MOVE_TIME, gen, **opts)

    elif version == 1:
        assert False, "Deprecated with puct1 removal"

    else:
        assert False, "invalid version: %s" % version


def elo_dump_and_save(filename, ratings, verbose=False):
    if verbose:
        print "ELO DUMP:"
        print "========="

    # sort in place, so also benefit by saving in this order
    ratings.players.sort(reverse=True,
                         key=operator.attrgetter("elo"))
    if verbose:
        for p in ratings.players:
            print p.name, p.played, p.elo

    with open(filename, "w") as f:
        contents = at.attr_to_json(ratings, pretty=True)
        f.write(contents)


def choose_players(all_players, verbose=False):
    ''' will return None if no candidates '''

    all_players = [p for p in all_players if hasattr(p, "rating")]

    for count in CHOOSE_BUCKETS:
        candidates = [c for c in all_players if c.rating.played < count]
        if candidates:
            break
    else:
        return None

    dist = []
    for p in candidates:
        yet_to_play = max(1, 50 - p.rating.played)
        dist += [p] * yet_to_play

    random.shuffle(dist)
    first_player = dist.pop()

    # anyone as second player?  Better to match up based on expected score distance.

    def px(p0, p1):
        # the closer to 1.0, then better chance it will be a close game.
        z = 1.0 - 2 * abs(0.5 - probability(p.rating.elo,
                                            first_player.rating.elo))

        # XXX apply more temperature to less established players
        temp = max(2.0, 20.0 / (p0.rating.played + 1))

        # apply a temperature and return
        return z ** temp, p1

    dist = [px(first_player, p) for p in all_players if p != first_player]
    dist.sort(reverse=True)

    # exponential scaling K (higher more scaling)
    K = 200
    total = sum(K**x for x, _ in dist)
    over_this = random.random() * total

    if verbose:
        print [K**x for x, _ in dist]
        print "first_player", first_player, over_this, total

    second_player = None
    acc = 0

    for prob, p in dist:
        acc += K ** prob
        if verbose:
            print "NEXT", prob, acc, p

        if acc > over_this:
            second_player = p
            break

    if second_player is None:
        second_player = dist[-1][1]

    if verbose:
        print "second_player", second_player

    # who plays first?
    if random.random() > 0.5:
        return first_player, second_player
    else:
        return second_player, first_player


def gen_elo(match_info, all_players, filename, move_generator=None, verbose=False):
    if os.path.exists(filename):
        ratings = at.json_to_attr(open(filename).read())
    else:
        ratings = AllRatings(match_info.name)
        ratings.players.append(PlayerRating("random", fixed=True, elo=500.0))

    # add in all the players

    # slow add one playeer
    slow_add_count = 0
    for p in all_players:
        if verbose:
            print "Adding", p.get_name()

        playerinfo = None
        for info in ratings.players:
            if info.name == p.get_name():
                playerinfo = info

        if playerinfo is None:
            if slow_add_count >= MAX_ADD_COUNT:
                if verbose:
                    print "SKIPPING for now", playerinfo
                continue
            else:
                playerinfo = PlayerRating(p.get_name(), 0, STARTING_ELO)
                ratings.players.append(playerinfo)

        p.rating = playerinfo
        if playerinfo.played < 20:
            slow_add_count += 1

    # check no leftover ratings for players
    for rated_player in ratings.players:
        found = False
        for p in all_players:
            if rated_player.name == p.get_name():
                assert not found, "bad config %s" % rated_player.name
                found = True

        if not found:
            log.warning("Dangling rating in elo file: %s" % rated_player.name)

    # update the ratings with players
    elo_dump_and_save(filename, ratings)

    for i in range(NUM_GAMES):
        players = choose_players(all_players)
        if players is None:
            break

        player0, player1 = players

        moves = None
        if move_generator:
            moves = move_generator()

        # play the game
        try:
            res = match_info.play(players,
                                  MOVE_TIME,
                                  moves=moves,
                                  resign_score=RESIGN_PCT,
                                  verbose=True)

            (_, score0), (_, score1) = res[1]
            res_str = ""
            k = 42 * 2.5
            if score0 == 100:
                res_str = "1st player wins"
                player0_wins = True

            elif score1 == 100:
                res_str = "2nd player wins"
                player0_wins = False

            else:
                res_str = "Draws"
                k /= 2.0

                # fake a win for player with lower elo
                player0_wins = player0.rating.elo < player1.rating.elo

            res_str = "%s: %s (%.1f) / %s (%.1f) " % (res_str, player0.get_name(), player0.rating.elo,
                                                      player1.get_name(), player1.rating.elo)
            print res_str
            ratings.log.append(res_str)

        except MatchTooLong as exc:
            err = 'MatchTooLong, %s v %s' % (player0, player1)
            ratings.log.append(err)
            print "match aborted", exc
            continue

        except Exception as exc:
            print "match aborted", str(exc)
            raise

        def getk(r, o):
            if r.fixed:
                return 0.0

            if r.played < 20:
                return k * 2.5

            if r.played < 40:
                return k

            if r.played < 60:
                return k / 2.0

            if r.played > 60:
                kx = k / 2.5

            else:
                kx = k

            # extra penalty if o not established
            if o.played < 10:
                kx /= 10.0

            elif o.played < 20:
                kx /= 3.0

            elif o.played < 40:
                kx /= 2.0

            return kx

        player0.rating.played += 1
        player1.rating.played += 1

        (player0.rating.elo,
         player1.rating.elo) = next_elo_rating(player0.rating.elo,
                                               player1.rating.elo,
                                               getk(player0.rating, player1.rating),
                                               getk(player1.rating, player0.rating),
                                               player0_wins)

        elo_dump_and_save(filename, ratings)


###############################################################################

def transform_c6(move_str, fn):
    x = move_str[0]
    y = move_str[1:]

    x_cords = 'abcdefghijklmnopqrs'
    y_cords = [str(ii + 1) for ii in range(19)]

    x, y = fn(x, y, x_cords, y_cords)
    return "%s%s" % (x, y)


def move_generator_c6():
    if random.random() > 0.95:
        return None

    candidates = ['i11 k11', 'j11 l9', 'j12 k9', 'j8 k9', 'j8 l10', 'j11 j12', 'j9 k10', 'j9 k11']

    first_moves = random.choice(candidates)

    # rotate?
    do_rotations = random.choice([0, 1, 2, 3])
    for _ in range(do_rotations):
        rot_moves = [transform_c6(m, symmetry.rotate_90) for m in first_moves.split()]
        first_moves = " ".join(rot_moves)

    # reflect?
    if random.random() > 0.5:
        reflect_moves = [transform_c6(m, symmetry.reflect_horizontal)
                         for m in first_moves.split()]
        first_moves = " ".join(reflect_moves)

    first_moves = first_moves.replace(" ", "")
    return ['j10', first_moves]


def move_generator_hex13():
    if random.random() > 0.75:
        return None

    # XXX should generate a new table, don't think this is good enough any more

    candidates = ['c2', 'k12'] * 4
    candidates += "g11 h11 f11 h3 g3 f3".split() * 2
    candidates += ['a13', 'm1'] * 2
    candidates += "c12 k2 a4 m4 a11 a10 m12 a2 l12 b2".split()

    first_move = random.choice(candidates)

    first_move = "%s%s" % (first_move[0],
                           "abcdefghijklm"[int(first_move[1:]) - 1])
    return [first_move]


def move_generator_baduk():
    if random.random() > 0.75:
        return None
    return [random.choice(["ee", "dd", "df", "ff", "fd"])]


class Runner(object):
    """Run games and calculate ELO."""

    def connect6(self, filename="../data/elo/connect6.elo"):
        from ggpzero.battle.connect6 import MatchInfo

        match_info = MatchInfo()

        def dp(g, playouts, v):
            return define_player("connect6", g, playouts, v,
                                 max_dump_depth=1,
                                 dirichlet_noise_pct=0.15)

        # random = 500 elo
        random_player = get_player("r", MOVE_TIME)
        mcs_player = get_player("m", MOVE_TIME, max_iterations=800)
        simplemcts_player = get_player("s", MOVE_TIME, max_tree_playout_iterations=800)
        all_players = [random_player, mcs_player, simplemcts_player]

        man = manager.get_manager()

        num = 5
        gens = []
        while True:
            gen = "h1_%s" % num
            if not man.can_load("connect6", gen):
                break

            gens.append(gen)
            num += 10

        num = 145
        while True:
            gen = "h2_%s" % num
            if not man.can_load("connect6", gen):
                break

            gens.append(gen)
            num += 5

        gens += ["h1_183"]
        gens += ["h2_281", "h2_267", "h2_272", "h2_274", "h2_277", "h2_306", "h2_318", "h2_321"]
        all_players += [dp(g, 800, 3) for g in gens]

        gen_elo(match_info, all_players, filename,
                move_generator=move_generator_c6)

    def hex13(self, filename="../data/elo/hex13.elo"):
        from ggpzero.battle import hex

        match_info = hex.MatchInfo(13)

        # h1_229 was best from pre-july.  h1_50 was from 3rd June. h1_175 was from 21st june.
        # best_252 was 27th of August, I think some bigger model and includes historical data.

        # abandoned lines
        # h1_289 - oct 4
        # h2_260 - dec 19
        # h2_xxx - dec x
        # h4_339 - dec 22
        # h5_xxx - feb 2 (2019)
        # h6_xxx - feb xxx (2019)
        # hz_xxx - failed try at training from scratch (50 evals)

        # c1 - started from 229 data, ran at 200 evals
        # c2 - started from c1 data, ran at 300? evals

        random_player = get_player("r", MOVE_TIME)
        simplemcts_player = get_player("s", MOVE_TIME, max_tree_playout_iterations=800)
        all_players = [random_player, simplemcts_player]

        def dp(g, playouts, v):
            return define_player("hex13", g, playouts, v,
                                 depth_temperature_stop=1,
                                 fpu_prior_discount=0.25,
                                 dirichlet_noise_pct=0.15,
                                 fpu_prior_discount_root=0.25,
                                 max_dump_depth=1)

        gens = ["h1_25", "h1_50", "h1_75", "h1_100", "h1_125", "h1_150", "h1_175", "h1_200",
                "h1_229", "best_252", "h2_260", "h2_280", "h2_300", "h2_320", "h2_340", "h2_360",
                "h6_280", "h4_327", "h4_339", "h5_305", "h5_271", "h5_321"]

        new_c1 = ["c1_235", "c1_245", "c1_255", "c1_260", "c1_261", "c1_264", "c1_270", "c1_276",
                  "c1_279", "c1_285", "c1_288", "c1_292", "c1_309", "c1_312", "c1_316", "c1_334",
                  "c1_340", "c1_352", "c1_356", "c1_366", "c1_370", "c1_378", "c1_380", "c1_388",
                  "c1_390", "c1_394", "c1_398", "c1_400", "c1_410", "c1_420", "c1_428", "c1_432",
                  "c1_438", "c1_442", "c1_450", "c1_458", "c1_461", "c1_462", "c1_464", "c1_468",
                  "c1_470", "c1_471", "c1_473", "c1_478"]

        others = ["c2_201", "c2_203", "c2_205", "c2_208", "c2_209", "c2_212", "c2_216", "c2_221",
                  "c2_222", "c2_226", "c2_227", "c2_228", "c2_229", "c2_230", "c2_231", "c2_235",
                  "c2_239", "c2_242", "c2_248", "c2_250", "c2_275", "c2_277",
                  "d1_197", "d1x_310", "d1x_312", "d1x_317", "d1x_305",
                  "d2_110", "d2_112", "d2_139"]

        man = manager.get_manager()


        for name, num, incr in (["c2", 252, 3],
                                ["d1", 5, 10],
                                ["d2", 113, 3]):

            while True:
                gen = "%s_%s" % (name, num)
                if not man.can_load("hexLG13", gen):
                    print "FAILED TO LOAD GEN", gen
                    break

                gens.append(gen)
                num += incr

        all_players += [dp(g, 800, 3) for g in gens + new_c1 + others]

        gen_elo(match_info, all_players, filename,
                move_generator=move_generator_hex13)

    def baduk9_1(self, filename="../data/elo/baduk9_1.elo"):
        from ggpzero.battle import baduk
        match_info = baduk.MatchInfo(9)

        def dp(g, playouts, v):
            return define_player("baduk9", g, playouts, v,
                                 depth_temperature_stop=1,
                                 random_scale=0.8,
                                 dirichlet_noise_pct=0.15,
                                 fpu_prior_discount=0.25,
                                 fpu_prior_discount_root=0.15)

        all_players = [dp("h1_0", 42, 2)]
        gens = ("t1_420_orig", "h1_50", "h1_75", "h1_100", "h1_126", "h1_200", "h1_283",
                "t1_150", "t1_174", "t1_250", "t1_300", "t1_350", "t1_400", "t1_419",
                "c1_251", "c1_252", "c1_253", "c1_254", "c1_257", "c1_270", "c1_276", "c1_277")

        all_players += [dp(g, 800, 3) for g in gens]
        gen_elo(match_info, all_players, filename,
                move_generator=move_generator_baduk)

    def test_move_gen(self):
        from ggpzero.battle.connect6 import MatchInfo

        match_info = MatchInfo()

        sm = match_info.game_info.get_sm()

        while True:
            moves = move_generator_c6()
            print "moves", moves
            if moves is not None:
                _, _, bs, _ = match_info.make_moves(moves)
                sm.update_bases(bs)
                match_info.print_board(sm)

            raw_input()

    def test_move_gen2(self):
        from ggpzero.battle import hex

        match_info = hex.MatchInfo(13)

        sm = match_info.game_info.get_sm()

        while True:
            moves = move_generator_hex13()
            print "moves", moves
            if moves is not None:
                _, _, bs, _ = match_info.make_moves(moves)
                sm.update_bases(bs)
                match_info.print_board(sm)

            raw_input()

    def bt8(self, filename="../data/elo/bt8.elo"):
        from ggpzero.battle.bt import MatchInfo
        match_info = MatchInfo(8)

        def dp(g, playouts, v):
            return define_player("bt8", g, playouts, v,
                                 depth_temperature_stop=4,
                                 depth_temperature_start=4,
                                 random_scale=0.5)


        # 3 models ran on LG
        all_players = [dp(g, 800, 3) for g in ("x6_90",
                                               "x6_96",
                                               "x6_102",
                                               "x6_106",
                                               "x6_111",
                                               "x6_116",
                                               "x6_123",
                                               "x6_127",
                                               "x6_132",
                                               "x6_139",
                                               "x6_145",
                                               "x6_151",
                                               "x6_158",
                                               "x6_163",
                                               "x6_171",
                                               "x6_177")]

        kt_gens = ["kt1_1",
                   "kt1_2",
                   "kt1_3",
                   "kt1_4",
                   "kt1_5",
                   "kt1_7"]

        man = manager.get_manager()

        gens = []

        for name, num, incr in (["kt1", 10, 4],
                                ["kt3", 2, 3],
                                ["kt5", 2, 10],
                                ["f1", 1, 5],
                                ["az1", 2, 3]):
            while True:
                gen = "%s_%s" % (name, num)
                if not man.can_load("breakthrough", gen):
                    print "FAILED TO LOAD GEN", gen
                    break

                gens.append(gen)
                num += incr

        all_players += [dp(g, 800, 3) for g in gens]
        random_player = get_player("r", MOVE_TIME)
        mcs_player = get_player("m", MOVE_TIME, max_iterations=800)
        simplemcts_player = get_player("s", MOVE_TIME, max_tree_playout_iterations=800)
        all_players += [random_player, mcs_player, simplemcts_player]

        gen_elo(match_info, all_players, filename)

    def amazons(self, filename="../data/elo/amazons.elo"):
        man = manager.get_manager()

        from ggpzero.battle.amazons import MatchInfo
        match_info = MatchInfo()

        def dp(g, playouts, v):
            return define_player("az", g, playouts, v,
                                 dirichlet_noise_pct=0.15,
                                 depth_temperature_stop=4,
                                 depth_temperature_start=4,
                                 random_scale=0.9)

        gens = []
        for name, num, incr in (["h1", 7, 5],
                                ["h3", 7, 10],
                                ["f1", 1, 4]):
            while True:
                gen = "%s_%s" % (name, num)
                if not man.can_load("amazons_10x10", gen):
                    print "FAILED TO LOAD GEN", gen
                    break

                gens.append(gen)
                num += incr

        all_players = [dp(g, 800, 3) for g in gens]

        random_player = get_player("r", MOVE_TIME)
        mcs_player = get_player("m", MOVE_TIME, max_iterations=800)
        simplemcts_player = get_player("s", MOVE_TIME, max_tree_playout_iterations=800)
        all_players += [random_player, mcs_player, simplemcts_player]

        gen_elo(match_info, all_players, filename)


    def hex11(self, filename="../data/elo/hex11.elo"):
        man = manager.get_manager()

        from ggpzero.battle.hex import MatchInfo
        match_info = MatchInfo(11)

        def dp(g, playouts, v):
            return define_player("hex11", g, playouts, v,
                                 dirichlet_noise_pct=0.15,
                                 depth_temperature_stop=4,
                                 depth_temperature_start=4,
                                 random_scale=0.9)

        gens = []
        for name, num, incr in (["h1", 5, 8],
                                ["b1", 3, 5]):
            while True:
                gen = "%s_%s" % (name, num)
                if not man.can_load("hexLG11", gen):
                    print "FAILED TO LOAD GEN", gen
                    break

                gens.append(gen)
                num += incr

        all_players = [dp(g, 800, 3) for g in gens]

        random_player = get_player("r", MOVE_TIME)
        mcs_player = get_player("m", MOVE_TIME, max_iterations=800)
        simplemcts_player = get_player("s", MOVE_TIME, max_tree_playout_iterations=800)
        all_players += [random_player, mcs_player, simplemcts_player]

        gen_elo(match_info, all_players, filename)

    def reversi_8(self, filename="../data/elo/r8.elo"):
        man = manager.get_manager()

        from ggpzero.battle.reversi import MatchInfo8
        match_info = MatchInfo8()

        def dp(g, playouts, v):
            return define_player("r8", g, playouts, v,
                                 dirichlet_noise_pct=0.15,
                                 depth_temperature_stop=6,
                                 depth_temperature_start=6,
                                 random_scale=0.75,
                                 max_dump_depth=1)

        random_player = get_player("r", MOVE_TIME)
        mcs_player = get_player("m", MOVE_TIME, max_iterations=800)
        simplemcts_player = get_player("s", MOVE_TIME, max_tree_playout_iterations=800)
        all_players = [random_player, mcs_player, simplemcts_player]

        gens = []
        for name, num, incr in (["h3", 5, 20],
                                ["h5", 10, 20],
                                ['h6', 15, 20],
                                ["kt1", 3, 5],
                                ["kt2", 2, 5],
                                ["f1", 2, 6],
                                ["f2", 2, 6]):
            while True:
                gen = "%s_%s" % (name, num)
                if not man.can_load("reversi", gen):
                    print "FAILED TO LOAD GEN", gen
                    break

                gens.append(gen)
                num += incr

        all_players += [dp(g, 800, 3) for g in gens]

        gen_elo(match_info, all_players, filename)

    def reversi_10(self, filename="../data/elo/r10.elo"):
        man = manager.get_manager()

        from ggpzero.battle.reversi import MatchInfo10
        match_info = MatchInfo10()

        random_player = get_player("r", MOVE_TIME)
        mcs_player = get_player("m", MOVE_TIME, max_iterations=800)
        simplemcts_player = get_player("s", MOVE_TIME, max_tree_playout_iterations=800)
        all_players = [random_player, mcs_player, simplemcts_player]

        def dp(g, playouts, v):
            return define_player("r10", g, playouts, v,
                                 dirichlet_noise_pct=0.15,
                                 depth_temperature_stop=6,
                                 depth_temperature_start=6,
                                 max_dump_depth=1,
                                 random_scale=0.9)



        # note x1_7x was Scan first match
        # note x2_119 (or 121) was Scan second match (i think)

        # retrained new_x2_174... not sure what x2 state was in...
        # going to aggregate x2 and h3 and see if total makes stronger

        # @ 192 - massive jump in starting step 25 -> 83.

        # @ 211 - another jump, starting step 83 -> 100
        # @ 211 - crazy add change to neutralise policy pcts
        # current: x2_224 - assuming this was Scan 3rd match

        gens = []
        for name, num, incr in (["x1", 5, 10],
                                ["x2", 49, 10],
                                ['h5', 20, 10],
                                ["kt1", 3, 5]):
            while True:
                gen = "%s_%s" % (name, num)
                if not man.can_load("reversi_10x10", gen):
                    print "FAILED TO LOAD GEN", gen
                    break

                gens.append(gen)
                num += incr

        # ensure this one
        gens.append("x2_224")

        all_players += [dp(g, 800, 3) for g in gens]

        all_players.append(dp("h5_100", 800, 1))

        gen_elo(match_info, all_players, filename)

    def chess_15d(self, filename="../data/elo/chess_15d.elo"):
        def dp(g, playouts, v):
            return define_player("c_15f", g, playouts, v,
                                 dirichlet_noise_pct=0.15,
                                 depth_temperature_stop=6,
                                 depth_temperature_start=6,
                                 max_dump_depth=1,
                                 evaluation_multiplier_to_convergence=2.0,
                                 batch_size=8,
                                 noise_policy_squash_pct=0.5,
                                 noise_policy_squash_prob=0.25,
                                 fpu_prior_discount_root=0.1,
                                 fpu_prior_discount=0.2,
                                 random_scale=0.8)

        def dp_policy(g, v):
            return define_player("policy", g, 1, v,
                                 temperature=2.0,
                                 dirichlet_noise_pct=-1,
                                 depth_temperature_stop=6,
                                 depth_temperature_start=6,
                                 max_dump_depth=1,
                                 batch_size=1,
                                 noise_policy_squash_pct=-1,
                                 noise_policy_squash_prob=-1,
                                 random_scale=0.8)

        def dp_minimal(g, v):
            return define_player("minimal", g, 8, v,
                                 temperature=2.0,
                                 dirichlet_noise_pct=-1,
                                 depth_temperature_stop=6,
                                 depth_temperature_start=6,
                                 max_dump_depth=1,
                                 batch_size=1,
                                 fpu_prior_discount_root=0.05,
                                 fpu_prior_discount=0.05,
                                 noise_policy_squash_pct=-1,
                                 noise_policy_squash_prob=-1,
                                 random_scale=0.5)

        man = manager.get_manager()

        from ggpzero.battle import chess
        match_info = chess.MatchInfo(short_50=True)

        random_player = get_player("r", MOVE_TIME)
        mcs_player = get_player("m", MOVE_TIME, max_iterations=800)
        simplemcts_player = get_player("s", MOVE_TIME, max_tree_playout_iterations=800)
        all_players = [random_player]  # mcs_player , simplemcts_player

        gens = []
        for name, num, incr in (["c1", 5, 7],
                                ["kb1", 3, 5],
                                ["c2", 145, 5],
                                ["d1", 3, 5]):
            while True:
                gen = "%s_%s" % (name, num)
                if not man.can_load("chess_15d", gen):
                    print "FAILED TO LOAD GEN", gen
                    break

                gens.append(gen)
                num += incr

        gens.append("c2_367")
        all_players += [dp(g, 800, 3) for g in gens]
        all_players += [dp_policy(g, 3) for g in ["c2_375"]]
        all_players += [dp_minimal(g, 3) for g in ["c2_375"]]
        gen_elo(match_info, all_players, filename)


###############################################################################

if __name__ == '__main__':
    run(partial(fire.Fire, Runner), log_name_base="elo_")
