Connect 6
=========

Models here:

* h1 - first attempt at training
* h2 - forked h1, rebuilt database with symmetries

After approx gen h1_150, I added in all games from LG as historical data.  It didn't make any difference
to elo, as can see with approx gen h1_185.


elo graph
---------
Each model has ran a minimum of 100 games with a randomised matching algorithm continuous tournament.  Each match is
configured with a small amount of noise, and 800 evaluations per move.


* The y-axis is ELO.
* The x-axis is somewhat arbitrary in terms of compute.  Each model produced has a numeric value, which goes up incrementally as training progresses.
* random player has a fixed ELO of 500.


<img src="elo.png" width="95%"/>



