SELECT b.serving_path,b.status,count(DISTINCT b.logical_id) AS batches,
       avg(b.source_age) AS mean_source_age_hours,
       count(f.horizon) AS forecast_targets,
       count(f.horizon) FILTER (WHERE NOT EXISTS (
         SELECT 1 FROM forecast_error e WHERE e.logical_id=f.logical_id AND e.horizon=f.horizon
       )) AS pending_actual_targets
FROM forecast_batch b LEFT JOIN forecast f USING(logical_id)
WHERE b.release_id=? GROUP BY b.serving_path,b.status ORDER BY b.serving_path,b.status;
