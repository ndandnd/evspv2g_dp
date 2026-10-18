# Numerical population intervals and their propagation

For each configuration, a retained native full-family MIP bound L and an
independently physically replayed new feasible objective U give the numerical
interval [max(0,L-1e-6), U+1e-6]. These rely on floating-point solver bounds and
the documented replay tolerance; they are not exact-arithmetic certificates.
Missing bounds use only the universal nonnegative-cost lower bound. Missing or
rejected incumbents have no finite upper bound. Original rounded objectives and
the selected 1,800-second runs do not enter these intervals.

Write A=solar, B=solar_bess, C=v2g_fleet and D=v2g. The same inputs, costs and
individual boundaries give A>=B>=D and A>=C>=D: adding BESS or permitting truck
discharge only enlarges the feasible set. For each restrictive/flexible edge
X>=Y, update L_X=max(L_X,L_Y) and U_Y=min(U_Y,U_X). Repetition propagates these
valid implications; an inconsistent interval is an audit failure, not a value
to clip. The transfer of an upper bound is supported by independently replaying
the restrictive schedule in the more flexible configuration. Finite transferred
upper bounds carry their originating new worker identity.

For R=(A-B)/(A-D), assume A>D and A>=B>=D. Its partial derivatives with respect
to A,B,D have signs +,-,+. After nesting propagation, minimizing uses A=L_A,
D=L_D and B=min(U_B,L_A), giving max(0,L_A-U_B)/(L_A-L_D) when that denominator
is positive. Maximizing uses A=U_A, B=L_B and D=min(U_D,L_B), giving
(U_A-L_B)/(U_A-min(U_D,L_B)). The other intermediate configuration can be chosen
between D and A because of the propagated bounds. Unbounded or degenerate
endpoints conservatively use 0 and 1. The same argument applies with C instead
of B. Strict positivity is certified only when L_A>U_D; otherwise these bounds
are conditional on positive joint saving and no unconditional share is asserted.
For 1-B/A with A>0, monotonicity gives
[max(0,1-U_B/L_A), min(1,1-L_B/U_A)], with conservative [0,1] extensions at
unbounded or zero endpoints.

If each statistic r_i lies in [l_i,u_i], every order statistic is monotone in
each coordinate. Therefore the median lies in [median(l),median(u)]. All 270
bases are retained; with 270 observations each median is the arithmetic mean
of the 135th and 136th sorted endpoints. An unresolved base contributes its
full conservative interval, rather than being dropped. The gamma subsets are
fixed by the input manifest (30 at gamma<=0.35 and 100 at gamma>2).

A headline rounded to p decimal percentage places is supported only if the
entire numerical median interval is strictly inside the same rounding cell,
of width 10^(-p) percentage points. Boundary-touching intervals remain
unresolved. Any claim about a full-population share additionally requires every
joint denominator to be certified positive. Native optimal status alone never
collapses a nonzero recorded objective-bound interval to a point.
