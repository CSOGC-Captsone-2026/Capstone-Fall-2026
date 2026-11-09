
from pathlib import Path

import pandas as pd
from sklearn.ensemble import IsolationForest

DATA_PATH = (
    Path(__file__).resolve().parent.parent
    / "generator"
    / "data"
    / "original"
    / "readings.csv"
)


def evaluate_model(results):
    labels_path = DATA_PATH.parent / "labels.csv"
    labels = pd.read_csv(labels_path)

    labels["start"] = pd.to_datetime(labels["start"], utc=True)
    labels["end"] = pd.to_datetime(labels["end"], utc=True)

    #Reset the index so timestamps, sessions, and subjects are columns
    results = results.reset_index()
    results["timestamp"] = pd.to_datetime(results["timestamp"], utc=True)

    #assume normal until matches otherwise
    results["actual_anomaly"] = False

    for _, label in labels.iterrows():
        within_interval = (
            (results["session_id"] == label["session_id"])
            & (results["subject_id"] == label["subject_id"])
            & (results["timestamp"] >= label["start"])
            & (results["timestamp"] <= label["end"])
        )

        results.loc[within_interval, "actual_anomaly"] = True

    predicted = results["anomaly"] == -1
    actual = results["actual_anomaly"]

    tp = (predicted & actual).sum()
    fp = (predicted & ~actual).sum()
    fn = (~predicted & actual).sum()

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0

    print("\nModel Evaluation:")
    print(f"True positives: {tp}")
    print(f"False positives: {fp}")
    print(f"False negatives: {fn}")
    print(f"Precision: {precision:.2f}")
    print(f"Recall: {recall:.2f}")

def load_data():
    return pd.read_csv(DATA_PATH)

def prepare_data(df):
    #Convert individual sensor readings into feature columns
    features = df.pivot_table(
        index=["timestamp", "session_id", "subject_id"],
        columns="sensor_id",
        values="value"
    )
    features = features.sort_index()

    features = features.groupby(
        level=["session_id", "subject_id"]
    ).ffill().dropna()

    return features

def train_model(features):
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,
        random_state=42
    )

    model.fit(features)
    return model

if __name__ == "__main__":
    data = load_data()
    features = prepare_data(data)

    print(f"Total sensor readings: {len(data)}")
    print(f"Prepared observations: {len(features)}")
    print(f"Sensor features: {len(features.columns)}")

    if features.empty:
        raise ValueError("No complete observations available for training.")

    #Train the isolation forest model
    model = train_model(features)

    #predict anomalies in the prepared data
    predictions = model.predict(features)

    normal_count = (predictions == 1).sum()
    anomaly_count = (predictions == -1).sum()

    print("\nIsolation Forest Results:")
    print(f"Normal observations: {normal_count}")
    print(f"Flagged anomalies: {anomaly_count}")
    print(f"Anomaly percentage: {anomaly_count / len(predictions) * 100:.2f}%")

    #Show the timestamps
    results = features.copy()
    results["anomaly"] = predictions

    print("\nFirst 10 flagged anomalies:")
    print(results[results["anomaly"] == -1].head(10))

    evaluate_model(results)
