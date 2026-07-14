# Methods and validation

SegmentSignal implements a traditional, direct segmentation workflow: define the strategic purpose; separate segmentation bases from descriptors; prepare the basis matrix; form several candidate solutions; test robustness and parsimony; profile the chosen groups; and leave targeting and profitability as separate managerial decisions.

## Preparation

Let customer \(i\) have numeric basis value \(x_{ij}\) on variable \(j\). Missing numeric values use the sample median. If enabled, values are winsorized to the observed 1st and 99th percentiles. A non-negative column with sample skewness greater than 1 receives \(\log(1+x)\). By default each remaining numeric column is standardized (standardization can be disabled when all bases already share one meaningful scale, such as conjoint part-worths):

\[
z_{ij} = \frac{x_{ij}-\bar{x}_j}{s_j}.
\]

Categorical missing values become `Missing`. One-hot encoding groups infrequent categories (at least 1% of rows or two observations, capped at 20 output categories). Each one-hot block has one active level per customer, so its row norm does not grow with the number of categories. The user-controlled categorical weight multiplies every block; 1.0 leaves standard one-hot geometry unchanged.

These are defensible defaults, not uniquely correct choices. The export records what was applied.

## Candidate algorithms

### K-means

K-means finds \(k\) centroids that minimize within-cluster squared Euclidean distance:

\[
\sum_{g=1}^{k}\sum_{i \in C_g}\lVert z_i-\mu_g\rVert^2.
\]

SegmentSignal uses k-means++ initialization, 20 starts, a fixed seed, and up to 500 iterations. It is most natural for compact, roughly spherical groups in prepared numeric space.

### Gaussian mixture model

A finite Gaussian mixture estimates \(k\) multivariate normal components with full covariance matrices. It allows elliptical overlap and exposes posterior membership probabilities. SegmentSignal uses five starts, a small covariance regularizer, a fixed seed, and up to 500 iterations. AIC and BIC are exported as method-specific diagnostics but are not mixed into comparisons with non-likelihood algorithms. The UI omits this method when the basis contains categorical fields because an exact one-hot block is singular by construction and does not support a defensible full-Gaussian likelihood interpretation.

### Ward hierarchical clustering

Agglomerative Ward clustering starts with one customer per cluster and repeatedly joins the pair that produces the smallest increase in within-cluster sum of squares. It uses Euclidean geometry and is limited to 5,000 rows because memory and runtime grow quickly. The current UI defaults it on only for up to 1,500 rows.

### Spectral clustering

Spectral clustering builds a customer-to-customer similarity matrix with a Gaussian (RBF) kernel, \(\exp(-\gamma \lVert x_i - x_j \rVert^2)\) with \(\gamma = 1/p\) for \(p\) prepared columns, then partitions the similarity graph using the leading eigenvectors of its normalized graph Laplacian, followed by a k-means step on the embedded coordinates. Because it groups customers by similarity structure rather than by distance to a centroid, it can recover connected but non-spherical patterns — stretched, curved, or ring-like — that centroid methods split. SegmentSignal uses a fixed seed and 10 k-means restarts on the embedding, and limits the method to 2,500 customers because the dense similarity matrix and eigendecomposition grow quadratically. Spectral solutions provide no likelihood and no centroids for assigning future customers; membership confidence uses the same centroid-based approximation as K-means and Ward, which is a coarser fit for irregular shapes and should be read as orientation only.

### Hierarchy views (icicle and dendrogram)

For files up to 5,000 customers, the app computes a Ward linkage on the prepared matrix and shows the top of the merge tree in two classic forms: split boxes (an icicle chart, the whole base dividing into progressively smaller groups down to eight) and a truncated dendrogram (the last 25 merges, with collapsed group sizes in parentheses). These are the same views classic statistics packages print for hierarchical clustering. They support judgment about a plausible segment count; they are not a test, and the displayed hierarchy is Ward's — other methods in the comparison may group customers differently.

### Descriptive ANOVA and center distances

For the chosen solution, the app reports a one-way ANOVA per numeric basis variable (F, degrees of freedom, p-value, and eta squared) and the Euclidean distances between segment centers in prepared space. Because the clusters were constructed to maximize exactly these differences, the F statistics and p-values are descriptive rather than inferential — the same caveat classic SPSS cluster output prints. Eta squared is useful as a relative ranking of which variables separate the segments most.

## Diagnostics

### Silhouette

For customer \(i\), let \(a(i)\) be mean distance to its own cluster and \(b(i)\) the lowest mean distance to another cluster. The silhouette is:

\[
s(i) = \frac{b(i)-a(i)}{\max\{a(i),b(i)\}}.
\]

The reported score is the mean over all customers or a reproducible sample of 2,000. It ranges from -1 to 1; higher is better. Values depend strongly on data geometry and dimensionality, so no universal pass mark is used alone.

### Calinski–Harabasz and Davies–Bouldin

Calinski–Harabasz compares between-group and within-group dispersion; higher is better. Davies–Bouldin averages each group’s worst similarity to another group; lower is better. Both are descriptive internal indices and may favor different solutions.

### Subsample stability

Each candidate is refitted on repeated random 80% subsamples. Its labels on the retained customers are compared with their labels from the full-data solution using the adjusted Rand index (ARI). ARI corrects pairwise assignment agreement for chance and is invariant to arbitrary cluster numbers. The app reports mean ARI, its across-repeat standard deviation, and successful repeat count. At least four successful repeats are required for a Promising or Strong label. This is a robustness check, not external validation.

### Cross-method agreement

For a given \(k\), the app computes pairwise ARI between algorithms and reports the mean for each solution. Strong market structure should be less dependent on one precise algorithm, but different valid methods can disagree when they encode genuinely different assumptions.

### Segment substantiality and balance

The app reports smallest and largest segment shares. It also computes normalized entropy of the shares for the balanced score. Equal size is not a requirement; the purpose is to expose tiny or dominant groups before they receive names and budgets.

## Balanced evidence score

The top-candidate score is transparent and intentionally modest in authority. Components are clipped to \([0,1]\):

- separation: \(\text{clip}((\text{silhouette}+0.05)/0.55)\);
- resampling stability: mean ARI;
- substantiality and balance: 45% \(\text{clip}(\text{smallest share}/8\%)\), 25% normalized segment-size entropy, and 30% \(\text{clip}(\text{smallest segment count}/30)\);
- cross-method agreement when at least two methods succeed at the same \(k\);
- simplicity: \(\text{clip}(1-(k-2)/10)\).

The 0–100 score is:

\[
100(0.35S + 0.30R + 0.15M + 0.10A + 0.10P).
\]

When only one method succeeds at a given \(k\), cross-method agreement is unavailable. The remaining independent weights are renormalized to sum to 1; stability is not counted twice. The diagnostics record which scoring path was used.

The UI labels evidence using cautious heuristics:

| Label | Silhouette | Stability | Smallest segment | Sample guardrail |
|---|---:|---:|---:|---:|
| Strong | at least 0.45 | at least 0.80 | at least 5% | at least 300 total and 30 per segment |
| Promising | at least 0.25 | at least 0.65 | at least 3% | at least 100 total and 20 per segment |
| Exploratory | at least 0.12 | at least 0.50 | at least 2% | at least 5 per segment |
| Weak | otherwise | otherwise | otherwise |

These thresholds are not published laws. If every candidate is weak, the app explicitly reports that no reliable segmentation was found. A user may also reject a statistically strong result because it is not measurable, accessible, differentiable, actionable, profitable, fair, or aligned with organizational capabilities.

## Profiling and membership confidence

Numeric profiles report raw segment mean, median, overall mean, index with overall = 100, and the segment-mean difference in overall standard-deviation units. The snake chart plots those standardized differences but does not alter the fitted model.

Categorical profiles report up to the 20 most common overall levels, each level’s within-segment share, overall share, index with overall = 100, and whether it is the segment mode. Suggested names use positively overrepresented levels rather than merely repeating the most common overall category.

GMM confidence is the largest posterior component probability. For K-means, Ward, and spectral solutions, confidence is the distance to the nearest alternative centroid divided by the sum of that distance and the distance to the assigned cluster centroid. It usually ranges from 0.5 to 1.0; a Ward value below 0.5 transparently signals that the assigned hierarchical group is not the nearest final centroid. It is not the probability that a customer belongs to an objectively real type.

The 2-D map uses principal components fitted only for visualization. The explained-variance caption states how much prepared-space variance the two axes retain. PCA does not validate clusters.

## References

- Calinski, T., & Harabasz, J. (1974). A dendrite method for cluster analysis. *Communications in Statistics*, 3(1), 1–27.
- Davies, D. L., & Bouldin, D. W. (1979). A cluster separation measure. *IEEE Transactions on Pattern Analysis and Machine Intelligence*, PAMI-1(2), 224–227.
- Dolnicar, S., Grün, B., & Leisch, F. (2018). *Market Segmentation Analysis: Understanding It, Doing It, and Making It Useful*. Springer.
- Fraley, C., & Raftery, A. E. (2002). Model-based clustering, discriminant analysis, and density estimation. *Journal of the American Statistical Association*, 97(458), 611–631.
- Hubert, L., & Arabie, P. (1985). Comparing partitions. *Journal of Classification*, 2, 193–218.
- Lilien, G. L., Rangaswamy, A., & De Bruyn, A. (2017). *Principles of Marketing Engineering and Analytics* (3rd ed.). DecisionPro.
- MacQueen, J. (1967). Some methods for classification and analysis of multivariate observations. *Proceedings of the Fifth Berkeley Symposium on Mathematical Statistics and Probability*, 1, 281–297.
- Rousseeuw, P. J. (1987). Silhouettes: A graphical aid to the interpretation and validation of cluster analysis. *Journal of Computational and Applied Mathematics*, 20, 53–65.
- von Luxburg, U. (2007). A tutorial on spectral clustering. *Statistics and Computing*, 17(4), 395–416.
- Ward, J. H. (1963). Hierarchical grouping to optimize an objective function. *Journal of the American Statistical Association*, 58(301), 236–244.
- Wedel, M., & Kamakura, W. A. (2000). *Market Segmentation: Conceptual and Methodological Foundations* (2nd ed.). Kluwer Academic.
