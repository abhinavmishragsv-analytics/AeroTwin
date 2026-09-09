import nbformat as nbf
import os

os.makedirs('notebooks', exist_ok=True)

def write_nb(filename, title, code):
    nb = nbf.v4.new_notebook()
    nb.cells.append(nbf.v4.new_markdown_cell(f"# {title}"))
    nb.cells.append(nbf.v4.new_code_cell(code))
    output_path = os.path.join("notebooks", filename)
    with open(output_path, 'w', encoding='utf-8') as f:
        nbf.write(nb, f)

# Module 01: Prophet
c1 = """import pandas as pd
import numpy as np
from prophet import Prophet
import matplotlib.pyplot as plt

# Generate realistic aggregate flight delay data
dates = pd.date_range(start='2023-01-01', end='2024-01-01', freq='D')
delays = np.abs(np.sin(np.linspace(0, 10, len(dates))) * 15 + np.random.normal(5, 2, len(dates)))
df = pd.DataFrame({'ds': dates, 'y': delays})

m = Prophet(yearly_seasonality=True)
m.fit(df)
future = m.make_future_dataframe(periods=30)
forecast = m.predict(future)
fig = m.plot(forecast)
print("Prophet Forecast Model Trained.")
"""
write_nb('01_forecast_macro.ipynb', 'Module 01: Macro Delay Forecasting (Prophet)', c1)

# Module 02: XGBoost
c2 = """import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
import joblib

# Features: Hour, Visibility (m), Active Apron Count, Runway Queue Length
X = np.random.rand(1000, 4) * [24, 5000, 10, 5]
# Target: Taxi-out time (minutes)
y = (X[:, 0]*0.5) - (X[:, 1]*0.001) + (X[:, 2]*1.5) + (X[:, 3]*3) + np.random.normal(0, 2, 1000)

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.1)
model.fit(X_train, y_train)
print(f"XGBoost R2 Score: {model.score(X_test, y_test):.2f}")
joblib.dump(model, '02_taxi_xgboost.pkl')
"""
write_nb('02_taxitime_xgboost.ipynb', 'Module 02: Taxi-Time Prediction', c2)

# Module 07: Real Weather Disruption
c7 = """import pandas as pd
import requests
import io
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

print("Fetching LIVE METAR from Iowa Environmental Mesonet for VABO (Vadodara)...")
url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=VABO&data=tmpf,dwpf,sknt,vsby&year1=2023&month1=1&day1=1&year2=2024&month2=1&day2=1&tz=Etc%2FUTC&format=onlycomma&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=1&report_type=2"
res = requests.get(url)
df = pd.read_csv(io.StringIO(res.content.decode('utf-8'))).dropna()

df.columns = ['station', 'valid', 'temp_f', 'dew_f', 'wind_kt', 'vis_miles']
df['vis_miles'] = pd.to_numeric(df['vis_miles'], errors='coerce')
df = df.dropna()

df['ground_stop_risk'] = (df['vis_miles'] < 1.0).astype(int)
X = df[['temp_f', 'dew_f', 'wind_kt', 'vis_miles']]
y = df['ground_stop_risk']

if len(y) > 10:
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    clf = RandomForestClassifier(n_estimators=50)
    clf.fit(X_train, y_train)
    print(f"Weather Model Accuracy: {clf.score(X_test, y_test):.2f}")
    joblib.dump(clf, '07_weather_rf.pkl')
"""
write_nb('07_weather_disruption.ipynb', 'Module 07: Weather Ground-Stop Classifier', c7)
print("Successfully generated all Colab Notebooks.")
