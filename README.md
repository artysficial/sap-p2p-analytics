# Procure-to-Pay Analytics (SAP S/4HANA)

[![Tests and dashboard](https://github.com/artysficial/sap-p2p-analytics/actions/workflows/tests.yml/badge.svg)](https://github.com/artysficial/sap-p2p-analytics/actions/workflows/tests.yml)
[![Dashboard](https://img.shields.io/badge/dashboard-live-0071e3)](https://artysficial.github.io/sap-p2p-analytics/)

Procure-to-pay KPIs and exception detection on data shaped like SAP S/4HANA MM/FI tables, for the purchases of
the fictional Arunika Bank payment-security programme (HSM appliances, licences, consulting, security testing).

**[View the live dashboard →](https://artysficial.github.io/sap-p2p-analytics/)**

## What it shows

| KPI / check | How it is calculated | Where it lives in SAP |
| --- | --- | --- |
| Committed spend vs budget | Σ EKPO quantity × net price, by category and vendor | ME2N, ME2L |
| PR → PO cycle time | EKKO-BEDAT − EBAN-BADAT (average and P90) | ME5A / ME2N |
| First-time three-way match | invoice line vs PO line vs goods receipt, 5 % price tolerance | MIRO, MIR6 |
| On-time payment | clearing date vs net due date | FBL1N |
| Maverick buying | invoice date earlier than its PO (retro-PO) | MIR6 / ME2N |
| Duplicate invoices | same vendor, reference (XBLNR) and amount | MIR6, duplicate check |
| Split purchase orders | same vendor and day, each below the 250 M IDR approval limit, together above it | ME2N, release strategy |

Every exception on the dashboard comes with the transaction where it is resolved (MIGO, MRBR, MR8M…).

## Data model

`data/` holds CSV extracts named after the SAP tables they mirror: `LFA1`, `EBAN`, `EKKO`, `EKPO`, `MSEG`,
`RBKP`, `RSEG` and a simplified cleared-items table. They are produced by `p2p/generate.py` (seeded, so runs are
reproducible), which also plants the exceptions the analytics must find.

## Tests first, numbers second

`pytest` runs before the dashboard is built: primary keys, referential integrity, header-to-line reconciliation,
positive quantities, single currency, movement type 101, date logic, the three-way-match rule (including the
tolerance boundary) and detection of every planted exception. The tests caught two bugs in the generator while
this was built: a document dated after the extract date, and a regular order landing in the planted split group.

## Run it

```bash
pip install -r requirements.txt
python -m p2p.generate        # optional: regenerate data/
python -m pytest && python tools/build_dashboard.py
```

## Part of a case study

The SAP lens on the **Arunika Bank payment-security programme**: it buys what the
[project plan](https://artysficial.github.io/project-health-dashboard/) schedules, and the
[IT audit](https://artysficial.github.io/itgc-audit-analytics/) reviews SAP access for the same company.

Built by [Rahmadani Tyas Ningrum](https://artysficial.github.io/) · MIT licence
