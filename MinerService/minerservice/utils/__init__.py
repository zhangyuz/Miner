import json
import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from typing import Any, Dict

import matplotlib
import mplfinance as mpf
import numpy as np
from detonator import get_logger
from fastapi import WebSocket
from pandas import DataFrame

os.environ['MPLBACKEND'] = 'Agg'


matplotlib.use('Agg', force=True)

_l = get_logger('Utils', logging.DEBUG)


async def send_message(websocket: WebSocket, client_id: str, type: str, message: Dict[str, Any]):
    try:
        d = message.copy()
        d['type'] = type
        d['timestamp']: datetime.now().isoformat()
        _l.debug(f"{client_id} <- {json.dumps(d)}")
        await websocket.send_text(json.dumps(d))
    except Exception as e:
        _l.error(f"{client_id} <- {e}")
        raise Exception(f'Failed to send {message} to {client_id}') from e


app_password = os.environ.get('MAIL_SENDER_PWD', '')
mail_sender = os.environ.get('MAIL_SENDER', '')
mail_receivers = [r.strip()
                  for r in os.environ.get('MAIL_RECEIVERS', '').split(',')]


def send_email(message: Dict[str, str]):
    """Sends an email using a Gmail account with an App Password."""

    if not message:
        return

    _l.debug(message)

    if (not app_password) or (not mail_sender) or (not mail_receivers):
        _l.error(
            'No credentials provided. check "MAIL_SENDER_PWD", "MAIL_SENDER", "MAIL_RECEIVERS"')
        return

    msg = EmailMessage()
    msg['Subject'] = f'Signal @ {datetime.now()}'
    msg['From'] = 'Miner'
    msg['To'] = ', '.join(mail_receivers)
    msg.set_content(json.dumps(message))

    msg.make_mixed()

    image_html = ''
    for interval, tickers in message.items():
        for ticker in tickers:
            try:
                image = f'{interval}-{ticker}.png'
                with open(image, 'rb') as f:
                    # Read the file's data
                    image_mime = MIMEImage(f.read())
                    image_mime.add_header(
                        'Content-ID', image)
                    msg.attach(image_mime)
                    image_html += f'<p>{image}</p><img src="cid:{image}" style="max-width: 100%; height: auto; display: block; margin: 0 auto;"></br>'
                print("Attachment added successfully!")
            except FileNotFoundError:
                print(
                    f"Error: The file '{interval}-{ticker}.png' was not found. Make sure it's in the same directory.")
                return
    html_content = f'''
<html>
      <body>
        <p>Miner</p>
        {image_html}
      </body>
    </html>
'''
    msg.attach(MIMEText(html_content, 'html'))
    if mail_receivers:
        # Create a secure SSL context
        context = ssl.create_default_context()
        try:
            # Connect to the SMTP server and send the email
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
                server.login(mail_sender, app_password)
                server.sendmail(mail_sender, mail_receivers, msg.as_string())
                _l.debug(f'Email sent to {mail_receivers}')
            _l.info("Email sent successfully! ✅")
        except Exception as e:
            _l.error(f"Error: {e} ❌")
    else:
        _l.warning('No mail receiver from "MAIL_RECEIVERS"')


def plot_vegas_double_tunnel_signals(df: DataFrame, title: str = 'Vegas Double Tunnel Strategy', interval: str = '30m'):
    """
    Plots a candlestick chart with Vegas Double Tunnel EMAs and trade signals.

    Args:
        df: A pandas DataFrame containing OHLC bars and columns for the Vegas Tunnel EMAs
            and a 'signal' column with integer values.
        title: The title of the plot.
    """
    if df.empty:
        print("Warning: Cannot plot empty DataFrame")
        return

    if 'vegas_signal' not in df.columns:
        raise ValueError(
            "Input DataFrame must have a 'signal' column from the strategy function.")

    # Convert timestamp to datetime and set as index for mplfinance
    # df.index = pd.to_datetime(df['timestamp'])

    # Prepare bars for mplfinance. Columns must be capitalized.
    df_plot = df.rename(columns={'open': 'Open', 'high': 'High',
                        'low': 'Low', 'close': 'Close', 'volume': 'Volume'})

    # --- 1. Prepare additional plots for EMAs and signals ---

    # EMAs as a list of additional plots
    apds = [
        mpf.make_addplot(df_plot['ema12'], color='blue',
                         linestyle='--', label='EMA 12'),
        mpf.make_addplot(df_plot['ema10'], color='green',
                         linestyle='--', label='EMA 10'),
        mpf.make_addplot(df_plot['ema20'], color='blue',
                         linestyle='--', label='EMA 20'),
        mpf.make_addplot(df_plot['ema144'], color='lime', label='EMA 144'),
        mpf.make_addplot(df_plot['ema169'], color='cyan', label='EMA 169'),
        mpf.make_addplot(df_plot['ema576'], color='magenta', label='EMA 576'),
        mpf.make_addplot(df_plot['ema676'], color='orange', label='EMA 676'),
    ]

    # Plotting signals as scatter plots on the chart
    buy_signals = np.where(
        df_plot['vegas_signal'] == 2, df_plot['Low'] * 0.999, np.nan)
    sell_signals = np.where(
        df_plot['vegas_signal'] == -2, df_plot['High'] * 1.001, np.nan)
    increase_signals = np.where(
        df_plot['wedge_signal'] == 1, df_plot['Low'] * 0.999, np.nan)
    decrease_signals = np.where(
        df_plot['wedge_signal'] == -1, df_plot['High'] * 1.001, np.nan)

    # Convert signal arrays to mplfinance addplot dictionaries, but only if they contain actual signals
    signal_plots = []

    # Check if buy signals exist (not all NaN)
    if not np.all(np.isnan(buy_signals)):
        signal_plots.append(mpf.make_addplot(buy_signals, type='scatter', markersize=100, marker='^', color='green',
                                             label='Buy Signal'))

    # Check if sell signals exist (not all NaN)
    if not np.all(np.isnan(sell_signals)):
        signal_plots.append(mpf.make_addplot(sell_signals, type='scatter', markersize=100, marker='v', color='red',
                                             label='Sell Signal'))

    # Check if increase signals exist (not all NaN)
    if not np.all(np.isnan(increase_signals)):
        signal_plots.append(mpf.make_addplot(increase_signals, type='scatter', markersize=100, marker='^', color='blue',
                                             label='Increase Signal'))

    # Check if decrease signals exist (not all NaN)
    if not np.all(np.isnan(decrease_signals)):
        signal_plots.append(
            mpf.make_addplot(decrease_signals, type='scatter', markersize=100, marker='v', color='orange',
                             label='Decrease Signal'))

    # Add signal plots to the list of additional plots only if we have any
    if signal_plots:
        apds.extend(signal_plots)

    # --- 2. Plotting the final chart ---
    save_params = dict(
        fname=f'{interval}-{title}.png',
        dpi=300
    )

    mpf.plot(
        df_plot,
        type='candle',
        style='yahoo',
        title=title,
        ylabel='Price',
        addplot=apds,
        volume=True,
        figscale=1.5,
        figsize=(12, 8),
        tight_layout=True, savefig=save_params
    )
