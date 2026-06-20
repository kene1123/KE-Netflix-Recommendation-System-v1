import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import svds


class CollaborativeModel:
    def __init__(self, n_factors: int = 50):
        self.n_factors    = n_factors
        self.user_factors = None
        self.item_factors = None
        self.sigma        = None
        self.predictions  = None
        self.user_index   = {}   # user_id -> row index
        self.movie_index  = {}   # movie_id -> col index
        self.user_ids     = []
        self.movie_ids    = []
        self.global_mean  = 0.0

    def fit(self, ratings_df: pd.DataFrame) -> None:
        """
        ratings_df columns: user_id, movie_id, rating
        Builds sparse user-item matrix, applies SVD, reconstructs predictions.
        """
        self.user_ids   = sorted(ratings_df["user_id"].unique().tolist())
        self.movie_ids  = sorted(ratings_df["movie_id"].unique().tolist())
        self.user_index = {uid: i for i, uid in enumerate(self.user_ids)}
        self.movie_index = {mid: i for i, mid in enumerate(self.movie_ids)}
        self.global_mean = float(ratings_df["rating"].mean())

        rows = ratings_df["user_id"].map(self.user_index).values
        cols = ratings_df["movie_id"].map(self.movie_index).values
        vals = ratings_df["rating"].values - self.global_mean  # mean-centre

        matrix = csr_matrix(
            (vals, (rows, cols)),
            shape=(len(self.user_ids), len(self.movie_ids)),
        )

        k = min(self.n_factors, min(matrix.shape) - 1)
        U, sigma, Vt = svds(matrix, k=k)

        # Sort by descending singular value
        idx = np.argsort(sigma)[::-1]
        U, sigma, Vt = U[:, idx], sigma[idx], Vt[idx, :]

        self.user_factors = U
        self.sigma        = sigma
        self.item_factors = Vt

        # Full prediction matrix: add global mean back
        self.predictions = (U @ np.diag(sigma) @ Vt) + self.global_mean

    def predict(self, user_id: int, movie_id: int) -> float:
        u = self.user_index.get(user_id)
        m = self.movie_index.get(movie_id)
        if u is None or m is None:
            return self.global_mean
        return float(np.clip(self.predictions[u, m], 0.5, 5.0))

    def recommend_for_user(
        self,
        user_id: int,
        watched_ids: set[int],
        movie_id_to_title: dict[int, str],
        similar_users_top_movie: dict[int, str],
        top_n: int = 10,
    ) -> list[dict]:
        u = self.user_index.get(user_id)
        if u is None:
            return []

        scores = []
        for movie_id in self.movie_ids:
            if movie_id in watched_ids:
                continue
            m = self.movie_index[movie_id]
            pred = float(np.clip(self.predictions[u, m], 0.5, 5.0))
            scores.append((movie_id, pred))

        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[:top_n]

        bridge_movie = similar_users_top_movie.get(user_id, "")
        reason = (
            f"Users like you also watched {bridge_movie}"
            if bridge_movie else
            "Recommended based on users with similar taste"
        )

        return [
            {
                "user_id":        user_id,
                "movie_id":       mid,
                "score":          round(pred, 6),
                "algorithm_type": "collaborative",
                "reason":         reason,
            }
            for mid, pred in top
        ]

    def find_similar_users(self, user_id: int, top_k: int = 10) -> list[int]:
        """Return top_k most similar users by cosine similarity in factor space."""
        u = self.user_index.get(user_id)
        if u is None:
            return []
        user_vec = self.user_factors[u]
        norms    = np.linalg.norm(self.user_factors, axis=1)
        norms[norms == 0] = 1e-9
        sims = (self.user_factors @ user_vec) / (norms * np.linalg.norm(user_vec) + 1e-9)
        sims[u] = -1
        top_idx = np.argsort(sims)[::-1][:top_k]
        return [self.user_ids[i] for i in top_idx]

    def get_similar_users_bridge(
        self,
        ratings_df: pd.DataFrame,
        watched_by_user: dict[int, set[int]],
        movie_id_to_title: dict[int, str],
    ) -> dict[int, str]:
        """
        For each user, find the most-rated movie among their similar users
        that the current user hasn't seen. Used as the 'bridge' in reason text.
        """
        bridge: dict[int, str] = {}
        for user_id in self.user_ids:
            similar = self.find_similar_users(user_id, top_k=10)
            watched = watched_by_user.get(user_id, set())
            candidate_ratings = (
                ratings_df[
                    ratings_df["user_id"].isin(similar) &
                    ~ratings_df["movie_id"].isin(watched) &
                    (ratings_df["rating"] >= 4.0)
                ]
                .groupby("movie_id")["rating"]
                .mean()
                .sort_values(ascending=False)
            )
            if not candidate_ratings.empty:
                top_mid = int(candidate_ratings.index[0])
                bridge[user_id] = movie_id_to_title.get(top_mid, "")
        return bridge