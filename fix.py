from config.settings import get_connection
from pipelines.simulation import update_avg_watch_pct, log_stats

conn = get_connection()
update_avg_watch_pct(conn)
log_stats(conn)
conn.close()