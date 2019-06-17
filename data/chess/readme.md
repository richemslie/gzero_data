Chess
=====

* kb1 was trained with self play and historical data (concurrently 1-1 ratio).
* c1/c2 was trained via self play only.
* c2 forked from c1, slightly larger network.  Switched to using 3 value heads (black/white/draw) with cross entropy.

elo graph
---------
Each model has ran a minimum of 100 games with a randomised matching algorithm continuous tournament.  Each match is
configured with a small amount of noise, and 800 evaluations per move.


* The y-axis is ELO.
* The x-axis is somewhat arbitrary in terms of compute.  Each model produced has a numeric value, which goes up incrementally as training progresses.
* random player has a fixed ELO of -250.


<img src="elo.png" width="95%"/>



