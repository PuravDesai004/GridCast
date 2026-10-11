SELECT month, local_hour, weekday, count(*) AS observations,
       avg(value) AS mean_demand, min(value) AS minimum_demand, max(value) AS maximum_demand
FROM demand_scope WHERE observation_time>=? AND observation_time<?
GROUP BY month,local_hour,weekday ORDER BY month,local_hour,weekday;
