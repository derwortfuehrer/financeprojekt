from flask import Flask, render_template, request, redirect, url_for, send_file
import yfinance as yf
import pandas as pd
import matplotlib
from fpdf import FPDF
matplotlib.use('Agg')  # Wichtig für Server ohne GUI
import matplotlib.pyplot as plt
from yahooquery import search
import os
from io import BytesIO
import base64
from datetime import datetime, timedelta
from matplotlib.backends.backend_pdf import PdfPages

# --- App Initialisierung ---
app = Flask(__name__, template_folder='templates')

# --- Konfiguration & Daten ---
default_stocks = [
    {"ticker": "ALV.DE", "name": "Allianz SE"},
    {"ticker": "MUV2.DE", "name": "Münchener Rückversicherungs-Gesellschaft"},
    {"ticker": "RHM.DE", "name": "Rheinmetall"},
    {"ticker": "MTX.DE", "name": "MTU Aero Engines"},
    {"ticker": "IWDA.AS", "name": "Core MSCI World"},
    {"ticker": "CEK.DE", "name": "CeoTronics"},
    {"ticker": "AAPL", "name": "Apple"},
    {"ticker": "EEM", "name": "MSCI Emerging Markets"},
    {"ticker": "EMIM.AS", "name": "Core MSCI EM IMI"}
]

session_stocks = default_stocks.copy()

# --- Hilfsfunktionen ---

def get_stock_data(ticker, name, years_back=0.5):
    """Holt historische Aktienkurse je nach Zeitraum."""
    try:
        stock = yf.Ticker(ticker)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years_back * 365)
        history = stock.history(start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'))
        if history.empty:
            print(f"Warnung: Keine Daten für {ticker} ({name}) erhalten.")
            return None
        return history
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten für {ticker} ({name}): {e}")
        return None

def calculate_sma(data, price_column='Close', window=10):
    """Berechnet den einfachen gleitenden Durchschnitt."""
    if data is None or price_column not in data.columns:
        return None
    data[f'SMA_{window}'] = data[price_column].rolling(window=window).mean()
    return data

def find_cross_signals(data, price_column='Close'):
    """Findet Kauf- und Verkaufssignale basierend auf SMA."""
    signals = []
    close = data[price_column]
    sma = data[f'SMA_10']

    for i in range(1, len(data)):
        if close.iloc[i-1] < sma.iloc[i-1] and close.iloc[i] > sma.iloc[i]:
            signals.append((data.index[i], close.iloc[i], 'buy'))
        elif close.iloc[i-1] > sma.iloc[i-1] and close.iloc[i] < sma.iloc[i]:
            signals.append((data.index[i], close.iloc[i], 'sell'))
    return signals

def find_support_resistance(data, price_column='Close'):
    """Bestimmt Unterstützung und Widerstand als wichtige Hoch- und Tiefpunkte."""
    highs = data['High'].rolling(window=20).max()
    lows = data['Low'].rolling(window=20).min()

    resistance = highs.max()
    support = lows.min()
    return support, resistance

def create_chart(data, name, ticker, price_column='Close'):
    """Erstellt den Chart mit Signalen, Dividendenpunkten, Beschriftungen und Linien."""
    if data is None or data.empty or price_column not in data.columns:
        print(f"Fehler: Unzureichende Daten für {name} ({ticker}).")
        return None

    signals = find_cross_signals(data, price_column)
    support, resistance = find_support_resistance(data, price_column)

    # Dividenden laden
    try:
        stock = yf.Ticker(ticker)
        dividends = stock.dividends
    except Exception as e:
        print(f"Fehler beim Abrufen der Dividenden für {ticker}: {e}")
        dividends = None

    plt.figure(figsize=(14, 8))
    plt.plot(data.index, data[price_column], label='🔵 Schlusskurs', color='blue')
    plt.plot(data.index, data[f'SMA_10'], label='🔴 10-Tage-SMA', color='red')

    # Kauf- und Verkaufssignale markieren
    for date, price, signal_type in signals:
        if signal_type == 'buy':
            plt.scatter(date, price, marker='^', color='green', s=100, label='🟢 Kauf' if '🟢 Kauf' not in plt.gca().get_legend_handles_labels()[1] else "")
        elif signal_type == 'sell':
            plt.scatter(date, price, marker='v', color='red', s=100, label='🔻 Verkauf' if '🔻 Verkauf' not in plt.gca().get_legend_handles_labels()[1] else "")

    # Widerstand / Unterstützung einzeichnen
    plt.axhline(y=resistance, color='purple', linestyle='--', label=f'Widerstand {resistance:.2f}')
    plt.axhline(y=support, color='orange', linestyle='--', label=f'Unterstützung {support:.2f}')

    # Dividendenpunkte + Beschriftung einzeichnen
    if dividends is not None and not dividends.empty:
        for date, div in dividends.items():
            if date in data.index:
                # Dividendenpunkt
                plt.scatter(date, data.loc[date, price_column], marker='D', color='gold', s=80, label='🟨 Dividende' if '🟨 Dividende' not in plt.gca().get_legend_handles_labels()[1] else "")
                # Kleine Beschriftung
                plt.annotate(f'Div: {div:.2f}€', 
                             (date, data.loc[date, price_column]), 
                             textcoords="offset points", 
                             xytext=(0,10), 
                             ha='center', fontsize=8, color='black')

    plt.title(f'{name} ({ticker}) - Kurs, SMA, Signale & Dividenden')
    plt.xlabel('Datum')
    plt.ylabel('Preis (€)')
    plt.legend(loc='best')
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()

    img = BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    img_base64 = base64.b64encode(img.getvalue()).decode('utf-8')
    plt.close()
    return img_base64

def get_dividends(ticker, years_back=0.5):
    """Holt die kumulierten Dividendenzahlungen für ein Wertpapier im Zeitraum."""
    try:
        stock = yf.Ticker(ticker)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years_back * 365)
        dividends = stock.dividends

        # Dividenden auf Zeitraum filtern
        dividends = dividends[(dividends.index >= start_date) & (dividends.index <= end_date)]
        return dividends.sum()
    except Exception as e:
        print(f"Fehler beim Abrufen der Dividenden für {ticker}: {e}")
        return 0.0



# --- Routen ---

@app.route('/correlation', methods=['GET', 'POST'])
def correlation():
    global session_stocks
    correlation_result = None
    chart = None
    error_message = None

    if request.method == 'POST':
        ticker1 = request.form.get('ticker1')
        ticker2 = request.form.get('ticker2')

        if not ticker1 or not ticker2:
            error_message = "Bitte wählen Sie zwei verschiedene Wertpapiere aus."
        elif ticker1 == ticker2:
            error_message = "Bitte wählen Sie zwei verschiedene Wertpapiere für die Korrelation aus."
        else:
            data1 = get_stock_data(ticker1, ticker1)
            data2 = get_stock_data(ticker2, ticker2)

            if data1 is None or data2 is None:
                error_message = "Für eines oder beide Wertpapiere konnten keine Kursdaten geladen werden."
            else:
                try:
                    # Gemeinsame Datenbasis
                    merged = pd.DataFrame({
                        ticker1: data1['Close'],
                        ticker2: data2['Close']
                    }).dropna()

                    corr_value = merged.corr().iloc[0, 1]
                    correlation_result = round(corr_value, 3)

                    # Scatter-Plot erstellen
                    plt.figure(figsize=(8, 6))
                    plt.scatter(merged[ticker1], merged[ticker2], alpha=0.7)
                    plt.title(f'Korrelation: {ticker1} vs. {ticker2}\nKorrelationskoeffizient: {correlation_result}')
                    plt.xlabel(ticker1)
                    plt.ylabel(ticker2)
                    plt.grid(True)
                    plt.tight_layout()

                    img = BytesIO()
                    plt.savefig(img, format='png')
                    img.seek(0)
                    chart = base64.b64encode(img.getvalue()).decode('utf-8')
                    plt.close()

                except Exception as e:
                    print(f"Fehler bei der Korrelationsberechnung: {e}")
                    error_message = "Fehler beim Berechnen der Korrelation."

    return render_template('correlation.html', stocks=session_stocks, correlation_result=correlation_result, chart=chart, error_message=error_message)


@app.route('/', methods=['GET', 'POST'])
def index():
    global session_stocks
    error_message = None
    search_results = []
    selected_ticker = None

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'search':
            query = request.form.get('query')
            if query:
                try:
                    results = search(query)
                    search_results = [
                        {"ticker": r.get("symbol"), "name": r.get("longname", r.get("shortname", r.get("symbol")))}
                        for r in results.get('quotes', []) if r.get("symbol") and r.get("quoteType") in ["EQUITY", "ETF"]
                    ]
                    if not search_results:
                        error_message = "Keine passenden Ticker gefunden."
                except Exception as e:
                    error_message = f"Fehler bei der Suche: {e}"
            else:
                error_message = "Bitte geben Sie einen Suchbegriff ein."
        elif action == 'add':
            ticker_to_add = request.form.get('ticker')
            name_to_add = request.form.get('name')
            if ticker_to_add and name_to_add:
                if not any(stock['ticker'] == ticker_to_add for stock in session_stocks):
                    session_stocks.append({"ticker": ticker_to_add, "name": name_to_add})
                else:
                    error_message = f"{ticker_to_add} ist bereits in der Liste."
            else:
                error_message = "Ungültige Auswahl."
        elif action == 'remove':
            ticker_to_remove = request.form.get('ticker')
            if ticker_to_remove:
                session_stocks = [stock for stock in session_stocks if stock['ticker'] != ticker_to_remove]
        elif action == 'reset':
            session_stocks = default_stocks.copy()

    return render_template('index.html', stocks=session_stocks, search_results=search_results, error_message=error_message, selected_ticker=selected_ticker, enumerate=enumerate)

@app.route('/analyze', methods=['GET', 'POST'])
def analyze():
    global session_stocks
    charts = []

    years = 0.5
    use_adjusted = True

    if request.method == 'POST':
        years = float(request.form.get('years', 0.5))
        use_adjusted = request.form.get('use_adjusted') == 'yes'

    for stock in session_stocks:
        ticker = stock["ticker"]
        name = stock["name"]
        data = get_stock_data(ticker, name, years)

        if data is not None:
            if use_adjusted and 'Adj Close' in data.columns:
                data['Preis'] = data['Adj Close']
            else:
                data['Preis'] = data['Close']

            data = calculate_sma(data, price_column='Preis', window=10)

            if data is not None:
                chart_img = create_chart(data, name, ticker, price_column='Preis')
                if chart_img:
                    charts.append({"name": name, "ticker": ticker, "chart": chart_img})
                else:
                    charts.append({"name": name, "ticker": ticker, "chart": None, "error": "Chart konnte nicht erstellt werden."})
            else:
                charts.append({"name": name, "ticker": ticker, "chart": None, "error": "SMA konnte nicht berechnet werden."})
        else:
            charts.append({"name": name, "ticker": ticker, "chart": None, "error": "Daten konnten nicht abgerufen werden."})

    return render_template('analyze.html', charts=charts)

@app.route('/erbrecht')
def erbrecht_rechner():
    return render_template('erbrecht.html')

@app.route('/compare', methods=['GET', 'POST'])
def compare():
    global session_stocks
    chart = None
    error_message = None
    perf_diff = None
    performance_table = None

    if request.method == 'POST':
        ticker1 = request.form.get('ticker1')
        ticker2 = request.form.get('ticker2')

        if not ticker1 or not ticker2:
            error_message = "Bitte wählen Sie zwei verschiedene Wertpapiere aus."
        elif ticker1 == ticker2:
            error_message = "Bitte wählen Sie zwei verschiedene Wertpapiere für den Vergleich aus."
        else:
            data1 = get_stock_data(ticker1, ticker1)
            data2 = get_stock_data(ticker2, ticker2)

            if data1 is None or data2 is None:
                error_message = "Für eines oder beide Wertpapiere konnten keine Kursdaten geladen werden."
            else:
                try:
                    norm1 = data1['Close'] / data1['Close'].iloc[0] * 100
                    norm2 = data2['Close'] / data2['Close'].iloc[0] * 100

                    perf1 = norm1.iloc[-1]
                    perf2 = norm2.iloc[-1]
                    perf_diff = perf1 - perf2

                    performance_table = [
                        {"ticker": ticker1, "performance": round(perf1 - 100, 2)},
                        {"ticker": ticker2, "performance": round(perf2 - 100, 2)}
                    ]

                    plt.figure(figsize=(12, 8))
                    plt.plot(norm1.index, norm1, label=f'{ticker1} (Start=100)', color='blue')
                    plt.plot(norm2.index, norm2, label=f'{ticker2} (Start=100)', color='green')
                    plt.title(f'Vergleich: {ticker1} vs. {ticker2}')
                    plt.xlabel('Datum')
                    plt.ylabel('Indexierter Kurs (Startwert = 100)')
                    plt.legend()
                    plt.grid(True)
                    plt.xticks(rotation=45)
                    plt.tight_layout()

                    img = BytesIO()
                    plt.savefig(img, format='png')
                    img.seek(0)
                    chart = base64.b64encode(img.getvalue()).decode('utf-8')
                    plt.close()
                except Exception as e:
                    print(f"Fehler beim Erstellen des Charts: {e}")
                    error_message = "Fehler beim Erstellen des Vergleichs-Charts."

    return render_template('compare.html', stocks=session_stocks, chart=chart, error_message=error_message, perf_diff=perf_diff, performance_table=performance_table)

@app.route('/correlation_erklaerung')
def correlation_erklaerung():
    return render_template('correlation_erklaerung.html')

@app.route('/bar_chart')
def bar_chart():
    global session_stocks
    years = 0.5  # Oder Zeitraum später auswählbar

    kursgewinne = []
    dividendenrenditen = []
    labels = []

    for stock in session_stocks:
        ticker = stock["ticker"]
        name = stock["name"]
        data = get_stock_data(ticker, name, years)

        if data is not None:
            if 'Adj Close' in data.columns:
                start_price = data['Adj Close'].iloc[0]
                end_price = data['Adj Close'].iloc[-1]
            else:
                    start_price = data['Close'].iloc[0]
                    end_price = data['Close'].iloc[-1]
            kursgewinn_prozent = ((end_price - start_price) / start_price) * 100

            dividends_total = get_dividends(ticker, years)
            dividenden_prozent = (dividends_total / start_price) * 100

            kursgewinne.append(kursgewinn_prozent)
            dividendenrenditen.append(dividenden_prozent)
            labels.append(name)

    # Balkendiagramm erzeugen
    x = range(len(labels))

    plt.figure(figsize=(14, 8))
    plt.bar(x, kursgewinne, width=0.4, label='Kursgewinn (%)', color='skyblue')
    plt.bar([i + 0.4 for i in x], dividendenrenditen, width=0.4, label='Dividendenrendite (%)', color='gold')

    plt.xlabel('Wertpapiere')
    plt.ylabel('Rendite in %')
    plt.title('Vergleich: Kursgewinne vs. Dividendenrenditen')
    plt.xticks([i + 0.2 for i in x], labels, rotation=45, ha='right')
    plt.legend()
    plt.grid(axis='y')
    plt.tight_layout()

    img = BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    encoded_img = base64.b64encode(img.getvalue()).decode('utf-8')
    plt.close()

    return render_template('bar_chart.html', bar_chart=encoded_img)
@app.route('/summary')
def summary():
    global session_stocks
    years = 0.5  # Standard-Zeitraum

    summary_data = []

    for stock in session_stocks:
        ticker = stock["ticker"]
        name = stock["name"]
        data = get_stock_data(ticker, name, years)

        if data is not None:
            if 'Adj Close' in data.columns:
                start_price = data['Adj Close'].iloc[0]
                end_price = data['Adj Close'].iloc[-1]
            else:
                start_price = data['Close'].iloc[0]
                end_price = data['Close'].iloc[-1]

            kursgewinn_prozent = ((end_price - start_price) / start_price) * 100

            dividends_total = get_dividends(ticker, years)
            gesamtrendite = kursgewinn_prozent + (dividends_total / start_price * 100)

            summary_data.append({
                "name": name,
                "ticker": ticker,
                "start_price": round(start_price, 2),
                "end_price": round(end_price, 2),
                "kursgewinn_prozent": round(kursgewinn_prozent, 2),
                "dividenden_total": round(dividends_total, 2),
                "gesamtrendite": round(gesamtrendite, 2)
            })

    return render_template('summary.html', summary_data=summary_data)



from fpdf import FPDF

@app.route('/summary_pdf')
def summary_pdf():
    global session_stocks
    years = 0.5  # Zeitraum

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(200, 10, txt="Aktien Zusammenfassung", ln=True, align='C')
    pdf.ln(10)

    # Tabellenkopf
    pdf.set_font("Arial", 'B', size=10)
    headers = ["Name", "Start (EUR)", "Ende (EUR)", "Kursgewinn (%)", "Dividende (EUR)", "Gesamtrendite (%)"]
    col_widths = [50, 25, 25, 30, 30, 30]

    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, header, 1, 0, 'C')
    pdf.ln()

    # Tabelleninhalt
    pdf.set_font("Arial", size=10)

    for stock in session_stocks:
        ticker = stock["ticker"]
        name = stock["name"]
        data = get_stock_data(ticker, name, years)

        if data is not None:
            if 'Adj Close' in data.columns:
                start_price = data['Adj Close'].iloc[0]
                end_price = data['Adj Close'].iloc[-1]
            else:
                start_price = data['Close'].iloc[0]
                end_price = data['Close'].iloc[-1]

            kursgewinn_prozent = ((end_price - start_price) / start_price) * 100
            dividends_total = get_dividends(ticker, years)
            gesamtrendite = kursgewinn_prozent + (dividends_total / start_price * 100)

            row = [
                f"{name} ({ticker})",
                f"{start_price:.2f}",
                f"{end_price:.2f}",
                f"{kursgewinn_prozent:.2f}",
                f"{dividends_total:.2f}",
                f"{gesamtrendite:.2f}"
            ]

            for i, item in enumerate(row):
                pdf.cell(col_widths[i], 10, item, 1, 0, 'C')
            pdf.ln()

    # PDF als Bytes holen
    pdf_output = pdf.output(dest='S').encode('latin1')

    return send_file(
        BytesIO(pdf_output),
        as_attachment=True,
        download_name="zusammenfassung.pdf",
        mimetype='application/pdf'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
