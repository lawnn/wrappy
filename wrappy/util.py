from __future__ import annotations

import os
from abc import ABCMeta, abstractmethod
from datetime import datetime, timedelta

try:
    import numpy as np
except ModuleNotFoundError:
    np = None

try:
    import pandas as pd
except ModuleNotFoundError:
    pd = None

try:
    import polars as pl
except ModuleNotFoundError:
    pl = None

plt = None

_NP_NAN = float("nan") if np is None else np.nan


def _require_numpy():
    if np is None:
        raise ModuleNotFoundError(
            "This utility requires `numpy`. Install it with `pip install \"wrappy[analytics]\"`."
        )


def _require_pandas():
    if pd is None:
        raise ModuleNotFoundError(
            "This utility requires `pandas`. Install it with `pip install \"wrappy[analytics]\"`."
        )


def _require_polars():
    if pl is None:
        raise ModuleNotFoundError(
            "This utility requires `polars`. Install it with `pip install \"wrappy[analytics]\"`."
        )


def _require_matplotlib():
    global plt
    if plt is not None:
        return
    try:
        from matplotlib import pyplot as pyplot
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "This utility requires `matplotlib`. Install it with `pip install \"wrappy[analytics]\"`."
        ) from exc
    plt = pyplot


def simple_regression(x: np.ndarray, y: np.ndarray, plot_graph=False, title: str = "Linear Regression",
                      x_label: str = "x", y_label: str = "y", output_dir: str = None, save_fig: bool = False):
    _require_numpy()

    r2 = np.corrcoef(x, y)[0, 1] ** 2
    if r2 == np.nan:
        r2 = 0

    if not plot_graph:
        return r2

    _require_matplotlib()

    N = len(x)
    p, cov, _ = np.polyfit(x, y, 1, cov=True)
    a = p[0]
    b = p[1]
    sigma_a = np.sqrt(cov[0, 0])
    sigma_b = np.sqrt(cov[1, 1])
    sigma_y = np.sqrt(1 / (N - 2) * np.sum([(a * xi + b - yi) ** 2 for xi, yi in zip(x, y)]))
    yy = a * x + b
    fig = plt.figure()
    fig.suptitle(title)
    ax = fig.add_subplot(111)
    ax.scatter(x, y, c="blue", s=20, edgecolors="blue", alpha=0.3)
    ax.plot(x, yy, color='r')
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.grid(which="major", axis="x", color="gray", alpha=0.5, linestyle="dotted", linewidth=1)
    ax.grid(which="major", axis="y", color="gray", alpha=0.5, linestyle="dotted", linewidth=1)
    ax.text(1.02, 0.04, f"y = {a:.3f} ± {sigma_a:.3f}x + {b:.3f} ± {sigma_b:.3f}\nsigma_y={sigma_y:.3f}\nlength={x.size}", transform=ax.transAxes)
    ax.text(0.788, 0.1, f"R**2={r2:.4f}", transform=ax.transAxes)
    ax.text(0.59, 0.04, f"ProportionCorrect={(np.sqrt(r2) + 1) / 2 * 100:.2f}%", transform=ax.transAxes)

    if save_fig:
        if output_dir is None:
            output_dir = f'./png'
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        plt.savefig(f'{output_dir}/{title}.png')
    plt.show()


def plot_corrcoef(arr1, arr2, output_dir: str = None, title: str = None, x: str = 'indicator',
                  y: str = 'Return', save_fig: bool = False):
    """
    plot_corrcoef(past_returns, future_returns, output_dir='my_favorite/1', title='comparison', save_fig=True)
    事前にデータ形成しておく
    例は下記のようにすればよい

    :例:pandasでの結合、欠損値の削除,要素数を同じにする方法(推奨される方法)
    a = pd.concat([arr1, arr2], axis=1).dropna(how='any')

    :例:numpyでの結合,欠損値の削除,要素数を同じにする方法(行が合わなくなるので非推奨)
    a = np.vstack([arr1, arr2]) # 縦に結合
    a = a[:, ~np.isnan(a).any(axis=0)]  # 欠損値の削除
    print(a)

    :param x: str
    :param y: str
    :param arr1: ndarray
    :param arr2: ndarray
    :param output_dir: png/comparison
    :param title: EXAMPLE
    :param save_fig: True or False
    :return:
    """

    _require_numpy()
    _require_pandas()
    _require_matplotlib()

    if output_dir is None:
        output_dir = f'./png/'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if isinstance(arr1, (pd.DataFrame, pd.Series)):
        arr1 = arr1.to_numpy()
    if isinstance(arr2, (pd.DataFrame, pd.Series)):
        arr2 = arr2.to_numpy()

    correlation = np.corrcoef(arr1, arr2)[1, 0]
    r2 = correlation ** 2

    if title is None:
        title = 'Correlation'

    # 頻出する総和を先に計算
    N = len(arr2)
    # Nxy = np.sum([xi * yi for xi, yi in zip(arr1, arr2)])
    # Nx = np.sum([xi for xi, yi in zip(arr1, arr2)])
    # Ny = np.sum([yi for xi, yi in zip(arr1, arr2)])
    # Nx2 = np.sum([xi * xi for xi, yi in zip(arr1, arr2)])

    # 係数
    # a = (N * Nxy - Nx * Ny) / (N * Nx2 - Nx ** 2)
    # b = (Nx2 * Ny - Nx * Nxy) / (N * Nx2 - Nx ** 2)
    #
    # Yの誤差
    # sigma_y = np.sqrt(1 / (N - 2) * np.sum([(a * xi + b - yi) ** 2 for xi, yi in zip(arr1, arr2)]))
    #
    # 係数の誤差
    # sigma_a = sigma_y * np.sqrt(N / (N * Nx2 - Nx ** 2))
    # sigma_b = sigma_y * np.sqrt(Nx2 / (N * Nx2 - Nx ** 2))

    p, cov, _ = np.polyfit(arr1, arr2, 1, cov=True)
    a = p[0]
    b = p[1]
    sigma_a = np.sqrt(cov[0, 0])
    sigma_b = np.sqrt(cov[1, 1])

    # Yの誤差
    sigma_y = np.sqrt(1 / (N - 2) * np.sum([(a * xi + b - yi) ** 2 for xi, yi in zip(arr1, arr2)]))

    y2 = a * arr1 + b

    fig = plt.figure()
    fig.suptitle(title)
    ax = fig.add_subplot(111)
    ax.scatter(arr1, arr2, c="blue", s=20, edgecolors="blue", alpha=0.3)
    ax.plot(arr1, y2, color='r')
    ax.set_xlabel(f"{x}")
    ax.set_ylabel(f"{y}")
    ax.grid(which="major", axis="x", color="gray", alpha=0.5, linestyle="dotted", linewidth=1)
    ax.grid(which="major", axis="y", color="gray", alpha=0.5, linestyle="dotted", linewidth=1)
    ax.text(1.02, 0.04,
            f"y = {a:.3f} \u00B1 {sigma_a:.3f} x + {b:.3f} \u00B1 {sigma_b:.3f}\nsigma$_y$={sigma_y:.3f}",
            transform=ax.transAxes)
    ax.text(0.83, 0.16, f"IC={correlation:.4f}", transform=ax.transAxes)
    ax.text(0.788, 0.1, f"R**2={r2:.4f}", transform=ax.transAxes)
    ax.text(0.59, 0.04, f"ProportionCorrect={(abs(correlation) + 1) / 2 * 100:.2f}%", transform=ax.transAxes)

    if save_fig:
        plt.savefig(f'{output_dir}/{title}.png')

    plt.show()

def np_shift(arr, num=1, fill_value=_NP_NAN):
    _require_numpy()
    result = np.empty_like(arr)
    if num > 0:
        result[:num] = fill_value
        result[num:] = arr[:-num]
    elif num < 0:
        result[num:] = fill_value
        result[:num] = arr[-num:]
    else:
        result[:] = arr
    return result

def np_stack(x,y):
    _require_numpy()
    z = np.column_stack((x,y))
    z = z[~np.isnan(z).any(axis=1)]
    return z[:,0], z[:,1]

def resample_ohlc(org_df: pd.DataFrame, timeframe):
    _require_pandas()
    df = org_df.resample(f'{timeframe * 60}S').agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
    df['close'] = df['close'].fillna(method='ffill')
    df['open'] = df['open'].fillna(df['close'])
    df['high'] = df['high'].fillna(df['close'])
    df['low'] = df['low'].fillna(df['close'])
    return df

def df_list(df: pl.DataFrame, start_date: datetime, interval: int, quantity: int, dt_col: str="") -> list:
    """
    Args:
        df (pl.DataFrame): _description_
        start_date (pl.Datetime): _description_
        interval (int): x日毎
        quantity (int): 必要な数
        dt_col (str, optional): daetime カラム名

    Returns:
        list: _description_
    """
    _require_polars()

    # 日付リストを生成する
    date_list = [start_date + timedelta(days=interval*i)
                for i in range(quantity)
                if start_date + timedelta(days=interval*i) <= df[dt_col].max()]

    # DataFrameリストを生成する
    return [df.filter((pl.col(dt_col).ge(start_date)) & (pl.col(dt_col).lt(end_date)))
            for start_date, end_date in [(date_list[i], date_list[i+1])
                for i in range(0, len(date_list)-1, interval)] + ([ (date_list[-2], date_list[-1]) ]
                    if len(date_list) % interval != 1 else [])]

def trades_to_historical(df: pd.DataFrame, period: str = '1S'):
    _require_numpy()
    _require_pandas()

    if 'side' in df.columns:
        df['side'] = df['side'].mask(df['side'] == 'Buy', 'buy')
        df['side'] = df['side'].mask(df['side'] == 'BUY', 'buy')
        df['side'] = df['side'].mask(df['side'] == 'OrderSide.BUY', 'buy')
        df['side'] = df['side'].mask(df['side'] == 'Sell', 'sell')
        df['side'] = df['side'].mask(df['side'] == 'SELL', 'sell')
        df['side'] = df['side'].mask(df['side'] == 'OrderSide.SELL', 'sell')

        df["buyVol"] = np.where(df['side'] == 'buy', df['size'], 0)
        df["sellVol"] = np.where(df['side'] == 'sell', df['size'], 0)
        df_ohlcv = pd.concat([df["price"].resample(period).ohlc().ffill(),
                              df["size"].resample(period).sum(),
                              df["buyVol"].resample(period).sum(),
                              df["sellVol"].resample(period).sum()
                              ], axis=1)
        df_ohlcv.columns = ['open', 'high', 'low', 'close', 'volume', 'buyVol', 'sellVol']
    elif 'm' in df.columns:
        df['T'] = df['T'] / 1000
        df['T'] = pd.to_datetime(df['T'].astype(int), unit='s', utc=True, infer_datetime_format=True)
        df = df.set_index('T')
        df.index = df.index.tz_localize(None)
        df['m'] = df['m'].mask(df['m'] is True, 'buy')
        df['m'] = df['m'].mask(df['m'] is False, 'sell')
        df["buyVol"] = np.where(df['m'] == 'buy', df['q'], 0)
        df["sellVol"] = np.where(df['m'] == 'sell', df['q'], 0)
        df_ohlcv = pd.concat([df["p"].resample(period).ohlc().ffill(),
                              df["q"].resample(period).sum(),
                              df["buyVol"].resample(period).sum(),
                              df["sellVol"].resample(period).sum()
                              ], axis=1)
        df_ohlcv.columns = ['open', 'high', 'low', 'close', 'volume', 'buyVol', 'sellVol']
    else:
        df_ohlcv = pd.concat([df["price"].resample(period).ohlc().ffill(),
                              df["size"].resample(period).sum(),
                              ], axis=1)
        df_ohlcv.columns = ['open', 'high', 'low', 'close', 'volume']
    return df_ohlcv

class Objective(metaclass=ABCMeta):
    def __init__(self, df: any, params: dict):
        if isinstance(df, list):
            self.df_list = df
        else:
            self.df = df
        self.params = params

    def __call__(self, trial):
        # ハイパーパラメータの設定
        config = {}
        for key, value in self.params.items():
            config[key] = trial.suggest_int(key, value[0], value[1], value[2])
        return self.optimization(**config)

    @abstractmethod
    def optimization(self, **kwargs):
        raise NotImplementedError
