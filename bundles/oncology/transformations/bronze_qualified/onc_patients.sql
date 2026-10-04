CREATE STREAMING TABLE onc_patients
AS SELECT * FROM STREAM(ariel_test.dev_ariel_y_bronze_raw.onc_patients)
