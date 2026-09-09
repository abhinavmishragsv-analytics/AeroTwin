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

c1 = """import pandas as pd
import numpy as np
from prophet import Prophet
dates = pd.date_range(start='2023-01-01', end='2024-01-01', freq='D')
df = pd.DataFrame({'ds': dates, 'y': np.random.normal(15, 5, len(dates))})
m = Prophet().fit(df)
print("Prophet Forecast Model Ready.")"""
write_nb('01_forecast_macro.ipynb', 'Module 01: Macro Delay Forecasting', c1)

c2 = """from xgboost import XGBRegressor
import numpy as np
X, y = np.random.rand(100, 4), np.random.rand(100)
model = XGBRegressor().fit(X, y)
print("XGBoost Taxi-Time Model Ready.")"""
write_nb('02_taxitime_xgboost.ipynb', 'Module 02: Taxi-Time Prediction', c2)

c3 = """from sklearn.cluster import KMeans
import numpy as np
X = np.random.rand(200, 2)
kmeans = KMeans(n_clusters=3, n_init=10).fit(X)
print("K-Means Congestion Clustering Ready.")"""
write_nb('03_cluster_kmeans.ipynb', 'Module 03: Congestion Clustering', c3)

c4 = """import networkx as nx
G = nx.erdos_renyi_graph(10, 0.5)
centrality = nx.betweenness_centrality(G)
print("NetworkX Delay Propagation Graph Ready.")"""
write_nb('04_graph_networkx.ipynb', 'Module 04: Delay Propagation Graph', c4)

c5 = """import simpy
env = simpy.Environment()
print("SimPy Queueing Engine Notebook Ready.")"""
write_nb('05_twin_simpy.ipynb', 'Module 05: SimPy Digital Twin Evaluation', c5)

c7 = """from sklearn.ensemble import RandomForestClassifier
import numpy as np
X, y = np.random.rand(100, 4), np.random.randint(0, 2, 100)
clf = RandomForestClassifier().fit(X, y)
print("Random Forest Weather Classifier Ready.")"""
write_nb('07_weather_disruption.ipynb', 'Module 07: Weather Ground-Stop Classifier', c7)

print("All 6 Colab Notebooks successfully generated in /notebooks.")
