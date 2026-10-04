# Forge Scholar

**Look behind the score. Decide what to teach next.**

Forge Scholar is an open-source education project from [Titans Forge](https://www.titansforge.tech/). The standalone classroom example lets you inspect fictional student answers, follow a shared fraction misunderstanding, and prepare a lesson that stays private until the teacher approves it.

## Try the classroom example

Python 3.11 or newer is recommended. From a fresh checkout:

```sh
git clone --branch feat/standalone-classroom-demo https://github.com/titans-forge/forge-scholar.git
cd forge-scholar
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local address printed by Streamlit. On Windows, activate with `.venv\Scripts\activate`.

1. **Class overview:** see eight fictional students and the two answer patterns.
2. **Student answers:** inspect the work behind each pattern, including `1/4 + 1/4 → 2/8`.
3. **Next lesson:** edit the suggested plan, save a draft, then review and approve the saved version.
4. **Student preview:** see the approved lesson. An unapproved draft stays hidden. Saving an edit withdraws the earlier approval until the teacher reviews it again.

The example includes a visual explanation of `1/4 + 1/4 = 2/4 = 1/2`. It uses saved fictional answers and explicit rules; it does not call an AI model or grade real students.

## Your data stays local

The classroom example saves to a separate `fictional-classroom.sqlite3` file in your user application-data directory. It does not read or modify a Forge Vault database. To run a disposable or separate classroom instance, set an explicit path before starting:

```sh
FORGE_SCHOLAR_DEMO_DB=/absolute/path/to/my-demo.sqlite3 python -m streamlit run app.py
```

The legacy Scholar backend uses its own `scholar.duckdb` in local application data. Override that separately with `FORGE_SCHOLAR_DB` before importing backend modules. See [DEPENDENCIES.md](DEPENDENCIES.md) for optional document readers.

## What is ready, and what is still a preview?

The standalone example is a working local demonstration with fictional data. The teacher/student switch is a preview control, not authentication. Keep it on localhost; production school use needs identity, authorization, privacy controls, and a real classroom evaluation.

The included larger teacher, assignment and administration modules remain developer source. Their original multi-page Forge workspace is not supplied as a complete application here. [VERIFICATION.md](VERIFICATION.md) records the checks performed and their limits.

## Develop and test

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The demo backend is in `scholar_demo.py`; the interface is in `app.py`. Tests use temporary databases. Report reproducible issues through GitHub.

## License

Apache 2.0 permits use, modification and commercial redistribution under its terms. See [LICENSE](LICENSE), [LICENSE-SCOPE.md](LICENSE-SCOPE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

[Source code](https://github.com/titans-forge/forge-scholar) · [Titans Forge](https://www.titansforge.tech/) · justiniancapone@titansforge.tech
