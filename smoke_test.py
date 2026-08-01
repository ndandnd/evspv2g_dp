"""Small deterministic verification of the main solution workflow."""

from colgen import column_generation
from master import solve_milp
from recreate_arxiv import build_instance


def main():
    instance = build_instance(2, 2.0, [(8, 14)])
    result = column_generation(
        instance,
        scenario="v2g",
        start="warm",
        do_milp=False,
        enrich=25,
        max_iter=2000,
        soc_mode="cyclic",
    )
    if not result["converged"]:
        raise RuntimeError(f"column generation did not converge: {result['term_reason']}")

    mip = solve_milp(
        instance,
        result["cols"],
        time_limit=120,
        battery_allowed=True,
        solver="cbc",
        soc_mode="cyclic",
    )
    artificial_mass = sum(
        mip.x[i]
        for i, column in enumerate(result["cols"])
        if column.kind == "artificial"
    )
    if str(mip.status).lower() != "optimal":
        raise RuntimeError(f"final MIP status is {mip.status}")
    if artificial_mass > 1e-8:
        raise RuntimeError(f"final MIP uses {artificial_mass:g} artificial coverage")

    print(
        {
            "status": mip.status,
            "tasks": instance.n_trips,
            "cg_converged": result["converged"],
            "termination": result["term_reason"],
            "artificial_mass": float(artificial_mass),
            "lp_obj": result["lp_obj"],
            "mip_obj": mip.obj,
            "columns": len(result["cols"]),
        }
    )


if __name__ == "__main__":
    main()
