CREATE STREAMING TABLE onc_appointments
AS SELECT * FROM STREAM(ariel_test.dev_ariel_y_bronze_raw.onc_appointments)
