import sys
import random
from collections import OrderedDict

import matplotlib.pyplot as plt

# 3rd party: https://github.com/google/python-fire
import fire

from ggpzero.util import attrutil as at


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


def main(genname_mapping, filename, gen_modifier=None, check_evals=800):
    ratings = at.json_to_attr(open(filename).read())
    genmodel_to_data = {}

    fig = plt.figure(figsize=(16,12))
    def get(name):
        if name not in genmodel_to_data:
            genmodel_to_data[name] = ([], [])
        return genmodel_to_data[name]

    for p in ratings.players:
        if "_" in p.name:
            if gen_modifier is not None:
                gen = gen_modifier(p.name)
            else:
                gen = int(p.name.split('_')[-1])

            was_evals = False
            for genname in genname_mapping:
                if genname in p.name:
                    datapoints = get(genname)
                    datapoints[0].append(gen)
                    datapoints[1].append(p.elo)

                    was_evals = str(check_evals) in p.name
                    break
            else:
                print "UNHANDLED", p.name
                continue

            txt = "* " if not was_evals else ""

            if p.played < Runner._elo_min:
                txt += "  %s" % p.played

            if txt:
                plt.text(gen, p.elo, txt)

        else:
            plt.plot(-10, [p.elo], "bx")
            txt = "  " + p.name
            if p.played < Runner._elo_min:
                txt += "  %s" % p.played

            plt.text(-10, p.elo, txt)

    for name, color in genname_mapping.items():
        datapoints = get(name)
        if len(datapoints[0]):
            plt.plot(datapoints[0], datapoints[1], color, label=name)

    plt.ylabel("ELO")
    plt.xlabel("Generation")
    mng = plt.get_current_fig_manager()
    plt.legend(loc='lower right')
    plt.show()


###############################################################################

class Runner(object):
    def __init__(self,
                 elo_min=100,
                 looptimes=1):
        Runner._elo_min = elo_min
        Runner._looptimes = looptimes

    def bt(self):

        def gen_modifier(name):
            gen = int(name.split('_')[-1])
            if "kt5" in name:
                gen /= 2
            return gen

        mapping = dict(
            x6="ro",
            f1="yo",
            kt1="bo",
            kt5="co",
            kt3="mo",
            az1="go")

        self._main(mapping, "../data/elo/bt8.elo", gen_modifier=gen_modifier)

    def hex13(self, do_long=False):
        def gen_modifier(name):
            gen = int(name.split('_')[-1])
            if not do_long and "c2_" in name:
                gen += 275

            elif "d2_" in name:
                gen += 450
            else:
                for prefix in ("h4", "h5", "h6"):
                    if prefix in name:
                        gen += 100
                        break

            return gen

        mapping = dict(
            c1="ro",
            h1="go",
            best="yx",
            d1_drop_="mx",
            h2="yo",
            h4="gx",
            h5="yx",
            h6="yx",
            c2="bo",
            d1_="mo",
            d1x="mx",
            d2="co")

        if do_long:
            self._main(mapping, "../data/elo/hex13_long.elo", gen_modifier=gen_modifier,
                       check_evals=3200)
        else:
            #, gen_modifier=gen_modifier
            self._main(mapping, "../data/elo/hex13.elo")


    def c6(self):
        mapping = dict(
            h1="ro",
            h2="bo")

        self._main(mapping, "../data/elo/connect6.elo")

    def az(self):
        mapping = dict(
            h1="ro",
            h3="go")

        self._main(mapping, "../data/elo/amazons.elo")

    def r8(self):
        mapping = dict(
            kt1="co",
            kt2="mo",
            f1="yo",
            f2="b^",
            h3="ro",
            h5="go",
            h6="bo")

        self._main(mapping, "../data/elo/r8.elo")

    def r10(self):
        mapping = dict(
            x1="co",
            x2="ro",
            h5="go",
            kt1="mo",
            h6="bo")

        self._main(mapping, "../data/elo/r10.elo")

    def chess_15d(self):
        mapping = OrderedDict(
            policy="mx",
            minimal="rx")
        mapping.update(
            c1="go",
            c2="mo",
            d1="co",
            kb1="bo")

        print mapping

        def gen_modifier(name):
            gen = int(name.split('_')[-1])
            if "c2" in name:
                gen += 200
            return gen

        self._main(mapping, "../data/elo/chess_15d.elo",
                   gen_modifier=gen_modifier)

    def baduk9(self):
        mapping = dict(
            t1="co",
            c1="ro",
            h1="go",
            c3h="rx")

        def gen_modifier(name):
            if name.endswith("_orig"):
                name = name.strip("_orig")
            if name.endswith("_bad"):
                name = name.strip("_bad")
            return int(name.split('_')[-1])

        self._main(mapping, "../data/elo/baduk9_1.elo",
                   gen_modifier=gen_modifier)

    def _main(self, *args, **kargs):
        for ii in range(self._looptimes):
            main(*args, **kargs)


if __name__ == "__main__":
    fire.Fire(Runner)


