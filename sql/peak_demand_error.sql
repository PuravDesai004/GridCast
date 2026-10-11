SELECT local_hour, weekday, count(*) AS paired_targets,
       avg(abs(prediction-actual)) AS peak_mae,
       sum(CASE WHEN prediction<actual THEN 1 ELSE 0 END) AS underpredicted_targets,
       sum(greatest(actual-prediction,0)) AS underprediction_sum,
       min(peak_threshold) AS minimum_training_peak_threshold,
       max(peak_threshold) AS maximum_training_peak_threshold
FROM evaluations WHERE split=? AND model=? AND actual>peak_threshold
GROUP BY local_hour,weekday ORDER BY local_hour,weekday;
