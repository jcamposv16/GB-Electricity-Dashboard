---
title: GB Electricity Dashboard
emoji: ⚡
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: "1.58.0"
app_file: app.py
pinned: false
---

# GB Electricity Dashboard

An interactive analytics dashboard for the Great Britain electricity
market, covering generation mix, interconnector flows, carbon
intensity, and price and quarterly analysis.

## Live demo

**[View the live dashboard on Hugging Face Spaces](https://huggingface.co/spaces/jcamposv16/gb-electricity-dashboard)**

## Features

- Generation Mix: half-hourly, daily, and monthly breakdowns by fuel type
- Generation by Main Fuel Group: generation aggregated into broader fuel categories
- Interconnector Flows: import and export flows across each GB interconnector
- Generation Flow: an animated live snapshot of grid power flows
- Quarterly Analysis: quarter-on-quarter trends across the generation mix
- Comparison Analysis: year-on-year comparisons of generation and price
- Carbon Intensity: a live regional map of carbon intensity across GB

## Data sources

Elexon BMRS (FUELHH generation, interconnector flows, and MID price),
the NESO SQL API, Nord Pool N2EX day-ahead prices, and the Carbon
Intensity API. The deployed database is a snapshot refreshed daily,
while the historical aggregates run back to 2020.

## Tech stack

Python, Streamlit, SQLite, Plotly, and Leaflet for the regional map.

## Notes

This is a portfolio project. The deployed data is a periodically
refreshed snapshot rather than live, real-time data.
