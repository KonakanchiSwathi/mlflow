import json
from pathlib import Path

import pytest
from promptflow import load_flow
from promptflow._sdk.entities._flow import Flow
from pyspark.sql import SparkSession

import mlflow
from mlflow import MlflowException
from mlflow.deployments import PredictionsResponse
from mlflow.pyfunc.scoring_server import CONTENT_TYPE_JSON

from tests.helper_functions import pyfunc_serve_and_score_model


@pytest.fixture(scope="module")
def spark():
    with SparkSession.builder.master("local[*]").getOrCreate() as s:
        yield s


def get_promptflow_example_model():
    flow_path = Path(__file__).parent / "flow_with_additional_includes"
    return load_flow(flow_path)


def test_promptflow_log_and_load_model():
    model = get_promptflow_example_model()
    with mlflow.start_run():
        logged_model = mlflow.promptflow.log_model(
            model, "promptflow_model", input_example={"text": "Python Hello World!"}
        )

    loaded_model = mlflow.promptflow.load_model(logged_model.model_uri)

    assert "promptflow" in logged_model.flavors
    assert logged_model.signature is not None
    assert str(logged_model.signature.inputs) == "['text': string]"
    assert str(logged_model.signature.outputs) == "['output': string]"
    assert isinstance(loaded_model, Flow)


def test_log_model_with_config():
    model = get_promptflow_example_model()
    model_config = {"connection.provider": "local"}
    with mlflow.start_run():
        logged_model = mlflow.promptflow.log_model(
            model, "promptflow_model", model_config=model_config
        )

    assert mlflow.pyfunc.FLAVOR_NAME in logged_model.flavors
    assert mlflow.pyfunc.MODEL_CONFIG in logged_model.flavors[mlflow.pyfunc.FLAVOR_NAME]
    logged_model_config = logged_model.flavors[mlflow.pyfunc.FLAVOR_NAME][
        mlflow.pyfunc.MODEL_CONFIG
    ]
    assert logged_model_config == model_config


def log_promptflow_example_model():
    model = get_promptflow_example_model()
    with mlflow.start_run():
        logged_model = mlflow.promptflow.log_model(model, "promptflow_model")
    return logged_model


def test_promptflow_model_predict_pyfunc():
    logged_model = log_promptflow_example_model()
    loaded_model = mlflow.pyfunc.load_model(logged_model.model_uri)
    # Assert pyfunc model
    assert "promptflow" in logged_model.flavors
    assert type(loaded_model) == mlflow.pyfunc.PyFuncModel
    # Assert predict with pyfunc model
    input_value = "Python Hello World!"
    result = loaded_model.predict({"text": input_value})
    expected_result = (
        f"Write a simple {input_value} program that displays the greeting message when executed.\n"
    )
    assert result == {"output": expected_result}


def test_promptflow_model_serve_predict():
    # Assert predict with promptflow model
    logged_model = log_promptflow_example_model()
    # Assert predict with serve model
    input_value = "Python Hello World!"
    response = pyfunc_serve_and_score_model(
        logged_model.model_uri,
        data=json.dumps({"inputs": {"text": input_value}}),
        content_type=CONTENT_TYPE_JSON,
        extra_args=["--env-manager", "local"],
    )
    expected_result = (
        f"Write a simple {input_value} program that displays the greeting message when executed.\n"
    )
    assert PredictionsResponse.from_json(response.content.decode("utf-8")) == {
        "predictions": {"output": expected_result}
    }


def test_promptflow_model_sparkudf_predict():
    # Assert predict with promptflow model
    logged_model = log_promptflow_example_model()
    # Assert predict with spark udf
    udf = mlflow.pyfunc.spark_udf(spark, logged_model.model_uri, result_type="string")
    input_value = "Python Hello World!"
    df = spark.createDataFrame([{"text": input_value}])
    df = df.withColumn("output", udf("text"))
    pdf = df.toPandas()
    expected_result = (
        f"Write a simple {input_value} program that displays the greeting message when executed.\n"
    )
    assert pdf["output"].tolist() == [expected_result]


def test_unsupported_class():
    mock_model = object()
    with pytest.raises(
        MlflowException, match="only supports instances loaded by ~promptflow.load_flow"
    ):
        with mlflow.start_run():
            mlflow.promptflow.log_model(mock_model, "mock_model_path")
