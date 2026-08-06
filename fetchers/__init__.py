"""fetchers package — 6 信号采集器 (华泰 6 信号框架)"""
from .crowding import fetch_crowding
from .sharpe import fetch_sharpe
from .ttm_2nd_deriv import fetch_ttm_2nd_deriv
from .copper_clad import fetch_copper_clad
from .capex_2nd_deriv import fetch_capex_2nd_deriv
from .earnings_surprise import fetch_earnings_surprise
