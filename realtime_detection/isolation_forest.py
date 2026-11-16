import argparse
from pathlib import Path

import pandas as pd
from sklearn.ensemble import IsolationForest

REPO = Path(__file__).resolve().parent.parent


def evaluate_model(results, labels_path):
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

def load_data(folder):
    return pd.read_csv(Path(folder) / "readings.csv")

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
    parser = argparse.ArgumentParser(description="Train on one dataset, test on another.")
    parser.add_argument("--train", default=str(REPO / "data" / "train"),
                        help="folder with readings.csv used for training")
    parser.add_argument("--test", default=str(REPO / "data" / "test"),
                        help="folder with readings.csv and labels.csv used for testing")
    args = parser.parse_args()

    train_data = load_data(args.train)
    test_data = load_data(args.test)
    train_features = prepare_data(train_data)
    test_features = prepare_data(test_data)

    print(f"Training readings: {len(train_data)} -> {len(train_features)} observations")
    print(f"Test readings:     {len(test_data)} -> {len(test_features)} observations")
    print(f"Sensor features: {len(train_features.columns)}")

    if train_features.empty or test_features.empty:
        raise ValueError("No complete observations available for training or testing.")

    #Both sets must have the same sensor columns in the same order
    test_features = test_features[train_features.columns]

    #Train the isolation forest model on the training set only
    model = train_model(train_features)

    #predict anomalies in the test set (data the model has never seen)
    predictions = model.predict(test_features)

    normal_count = (predictions == 1).sum()
    anomaly_count = (predictions == -1).sum()

    print("\nIsolation Forest Results (test set):")
    print(f"Normal observations: {normal_count}")
    print(f"Flagged anomalies: {anomaly_count}")
    print(f"Anomaly percentage: {anomaly_count / len(predictions) * 100:.2f}%")

    #Show the timestamps
    results = test_features.copy()
    results["anomaly"] = predictions

    print("\nFirst 10 flagged anomalies:")
    print(results[results["anomaly"] == -1].head(10))

    evaluate_model(results, Path(args.test) / "labels.csv")
