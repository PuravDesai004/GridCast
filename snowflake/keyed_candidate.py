"""USER-RUN registry adapter: the actual fixed candidate plus explicit batch row identity."""

import numpy as np
import pandas as pd
from snowflake.ml.model import custom_model


class KeyedCandidate(custom_model.CustomModel):
    @custom_model.inference_api
    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        candidate = self.context["candidate"]
        predictions = candidate.predict(frame[list(candidate.feature_names_in_)])
        return pd.DataFrame(
            {"row_id": frame["row_id"].to_numpy(), "prediction": np.maximum(predictions, 0.0)}
        )
