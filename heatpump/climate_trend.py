#!/usr/bin/python3
"""
Climate Trend Analysis from local heat pump ambient temperature sensor.
Data source: InfluxDB hp.hp_hourly.ambientTemperature
Computes tropical days (Tmax >= 30°C) and ice days (Tmax < 0°C) per year.
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from influxdb import DataFrameClient
import configparser
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'conf', 'config.ini')
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'climate_output')

os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_client():
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    return DataFrameClient(
        config['InfluxDb']['Host'],
        int(config['InfluxDb']['Port']),
        config['InfluxDb']['User'],
        config['InfluxDb']['Password'],
        config['InfluxDb']['Db']
    )


def fetch_data(client):
    """Fetch all ambientTemperature from hp_hourly."""
    print("Querying InfluxDB for hp_hourly.ambientTemperature ...")
    query = "SELECT ambientTemperature FROM hp_hourly ORDER BY time ASC"
    result = client.query(query)

    if 'hp_hourly' not in result or result['hp_hourly'].empty:
        print("ERROR: No data returned from hp_hourly. Check your database.")
        sys.exit(1)

    df = result['hp_hourly']
    df.index = pd.to_datetime(df.index)
    df = df.tz_localize(None) if df.index.tz is not None else df

    print(f"  Fetched {len(df)} hourly records")
    print(f"  Date range: {df.index.min()} -> {df.index.max()}")
    return df


def process_data(df):
    """Compute daily Tmax, then yearly tropical/ice day counts."""
    # Remove NaN / invalid
    df = df.dropna(subset=['ambientTemperature'])
    df = df[df['ambientTemperature'].between(-50, 60)]  # sanity filter

    # Daily max temperature
    daily = df.resample('D')['ambientTemperature'].max().dropna()
    daily.name = 'Tmax'
    daily_df = daily.to_frame()
    daily_df['date'] = daily_df.index.date
    daily_df['year'] = daily_df.index.year

    print(f"  {len(daily_df)} valid days after processing")

    # Save raw daily data
    raw_csv = os.path.join(OUTPUT_DIR, 'data_raw.csv')
    daily_df[['Tmax']].to_csv(raw_csv)
    print(f"  Saved raw daily data -> {raw_csv}")

    # Yearly aggregation
    yearly = daily_df.groupby('year').agg(
        tropical_days=('Tmax', lambda x: (x >= 30).sum()),
        ice_days=('Tmax', lambda x: (x < 0).sum()),
        total_days=('Tmax', 'count'),
        tmax_max=('Tmax', 'max'),
        tmax_min=('Tmax', 'min'),
    ).reset_index()

    # Coverage percentage; include years with at least 30 days
    yearly['coverage'] = yearly['total_days'] / 365 * 100
    full_years = yearly[yearly['total_days'] >= 30].copy()

    if len(full_years) == 0:
        print("WARNING: No year has >= 30 days of data. Using all years.")
        full_years = yearly.copy()

    # 5-year moving average (only if enough years)
    if len(full_years) >= 5:
        full_years['tropical_ma5'] = full_years['tropical_days'].rolling(5, center=True).mean()
        full_years['ice_ma5'] = full_years['ice_days'].rolling(5, center=True).mean()
    else:
        full_years['tropical_ma5'] = None
        full_years['ice_ma5'] = None

    # Save processed data
    proc_csv = os.path.join(OUTPUT_DIR, 'data_processed.csv')
    full_years.to_csv(proc_csv, index=False)
    print(f"  Saved processed data -> {proc_csv}")

    return full_years


def plot_data(df):
    """Create the climate trend chart."""
    fig, ax = plt.subplots(figsize=(14, 7))

    # Bar chart for actual values
    width = 0.35
    ax.bar(df['year'] - width/2, df['tropical_days'], width,
           color='#ff6b6b', alpha=0.6, label='Tropické dny (Tmax ≥ 30 °C)')
    ax.bar(df['year'] + width/2, df['ice_days'], width,
           color='#4dabf7', alpha=0.6, label='Ledové dny (Tmax < 0 °C)')

    # 5-year moving average lines
    if df['tropical_ma5'].notna().any():
        ax.plot(df['year'], df['tropical_ma5'], color='darkred', linewidth=2.5,
                label='Tropické dny – 5letý klouzavý průměr')
        ax.plot(df['year'], df['ice_ma5'], color='darkblue', linewidth=2.5,
                label='Ledové dny – 5letý klouzavý průměr')

    ax.set_xlabel('Rok', fontsize=12)
    ax.set_ylabel('Počet dní', fontsize=12)
    ax.set_title('Tropické a ledové dny – vlastní měření (ambientTemperature)\n'
                 'Zdroj: InfluxDB hp.hp_hourly, senzor tepelného čerpadla',
                 fontsize=13, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(axis='y', alpha=0.3)
    ax.set_xlim(df['year'].min() - 0.5, df['year'].max() + 0.5)

    # Annotate data coverage
    for _, row in df.iterrows():
        if row['coverage'] < 95:
            ax.annotate(f"{row['coverage']:.0f}%",
                        (row['year'], max(row['tropical_days'], row['ice_days']) + 1),
                        ha='center', fontsize=7, color='gray')

    plt.tight_layout()
    plot_path = os.path.join(OUTPUT_DIR, 'plot.png')
    plt.savefig(plot_path, dpi=150)
    print(f"  Saved chart -> {plot_path}")
    plt.close()


def write_analysis(df):
    """Write analysis summary."""
    md = f"""# Climate Trend Analysis – vlastní měření

## Zdroj dat
- **Databáze:** InfluxDB, `hp.hp_hourly`
- **Pole:** `ambientTemperature` (venkovní teplota ze senzoru tepelného čerpadla)
- **Agregace:** hodinové průměry → denní maximum (Tmax)
- **Rozsah:** {df['year'].min()} – {df['year'].max()}

## Metoda
1. Z InfluxDB stažena všechna hodinová data `ambientTemperature` z measurement `hp_hourly`
2. Odstraněny neplatné hodnoty (NaN, mimo rozsah -50..60 °C)
3. Výpočet denního maxima (Tmax) pro každý den
4. Roční počet:
   - **Tropické dny**: Tmax ≥ 30 °C
   - **Ledové dny**: Tmax < 0 °C
5. Klouzavý průměr za 5 let (pokud je dostatek dat)
6. Vyřazeny roky s méně než 300 dny dat

## Výsledky

| Rok | Tropické dny | Ledové dny | Pokrytí |
|-----|-------------|------------|---------|
"""
    for _, row in df.iterrows():
        md += f"| {int(row['year'])} | {int(row['tropical_days'])} | {int(row['ice_days'])} | {row['coverage']:.0f}% |\n"

    md += """
## Poznámky
- Data pochází z venkovního senzoru tepelného čerpadla, nikoli z meteorologické stanice.
- Přesnost měření závisí na umístění senzoru (stín, blízkost budovy apod.).
- Pro srovnání s oficiálními daty ČHMÚ (Praha-Ruzyně) lze použít veřejné datasety.
"""

    md_path = os.path.join(OUTPUT_DIR, 'analysis.md')
    with open(md_path, 'w') as f:
        f.write(md)
    print(f"  Saved analysis -> {md_path}")


def main():
    print("=" * 60)
    print("Climate Trend Analysis – vlastní měření")
    print("=" * 60)

    client = get_client()

    # Step 1: Fetch
    df = fetch_data(client)

    # Step 2: Process
    yearly = process_data(df)

    print("\nYearly summary:")
    print(yearly[['year', 'tropical_days', 'ice_days', 'total_days', 'coverage']].to_string(index=False))

    # Step 3: Plot
    plot_data(yearly)

    # Step 4: Analysis
    write_analysis(yearly)

    print("\n" + "=" * 60)
    print("Done. Output files in:", OUTPUT_DIR)
    print("=" * 60)


if __name__ == '__main__':
    main()
