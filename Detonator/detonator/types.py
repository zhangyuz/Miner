from typing import List, Literal, TypeAlias

IntradayInterval: TypeAlias = Literal['5m', '10m', '15m', '30m', '65m', '98m', '130m']
DailyInterval: TypeAlias = Literal['1d', '1wk', '1mo']
Intervals: TypeAlias = IntradayInterval | DailyInterval | List[IntradayInterval | DailyInterval]
