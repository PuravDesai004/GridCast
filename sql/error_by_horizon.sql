SELECT horizon, count(*) AS paired_targets,
       sum(abs(prediction-actual)) AS absolute_error_sum,
       sum(abs(actual)) AS actual_abs_sum,
       avg(abs(prediction-actual)) AS mae,
       100*sum(abs(prediction-actual))/nullif(sum(abs(actual)),0) AS wape,
       avg(prediction-actual) AS signed_bias,
       sum(CASE WHEN serving_path='seasonal_fallback' THEN 1 ELSE 0 END) AS fallback_targets
FROM evaluations WHERE split=? AND model=? GROUP BY horizon ORDER BY horizon;
