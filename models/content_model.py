import pandas as pd


class ContentModel:
    def __init__(self, df: pd.DataFrame, similarity_map: dict[int, list[tuple[int, float]]]):
        self.df             = df.reset_index(drop=True)
        self.similarity_map = similarity_map
        self._id_to_row     = {int(row["movie_id"]): row for _, row in df.iterrows()}

    def get_similar(self, movie_id: int, top_n: int = 50) -> list[tuple[int, float]]:
        return self.similarity_map.get(movie_id, [])[:top_n]

    def recommend_for_user(
        self,
        user_id: int,
        seed_movies: list[tuple[int, float, str]],
        watched_ids: set[int],
        top_n: int = 10,
    ) -> list[dict]:
        """
        seed_movies: list of (movie_id, combined_weight, title)
            combined_weight = (rating / 5) * watch_pct
            Higher weight = stronger signal on recommendations

        Returns recs with rich reason text.
        """
        scores:  dict[int, float] = {}
        sources: dict[int, list[str]] = {}

        for seed_id, weight, seed_title in seed_movies:
            for similar_id, sim_score in self.get_similar(seed_id):
                if similar_id in watched_ids:
                    continue
                combined = sim_score * weight
                if combined > scores.get(similar_id, 0):
                    scores[similar_id] = combined
                if similar_id not in sources:
                    sources[similar_id] = []
                if seed_title and seed_title not in sources[similar_id]:
                    sources[similar_id].append(seed_title)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]

        results = []
        for mid, score in ranked:
            titles = sources.get(mid, [])[:2]
            if len(titles) == 2:
                reason = f"Because you watched {titles[0]} and {titles[1]}"
            elif len(titles) == 1:
                reason = f"Because you watched {titles[0]}"
            else:
                row = self._id_to_row.get(mid)
                if row is not None:
                    top_genre = str(row["genres"]).split("|")[0]
                    reason = f"Because you enjoy {top_genre} films"
                else:
                    reason = "Recommended for you"

            results.append({
                "user_id":        user_id,
                "movie_id":       mid,
                "score":          round(score, 6),
                "algorithm_type": "content",
                "reason":         reason,
            })

        return results