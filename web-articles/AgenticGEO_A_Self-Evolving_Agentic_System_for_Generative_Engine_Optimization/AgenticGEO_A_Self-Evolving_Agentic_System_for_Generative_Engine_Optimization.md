# AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization

> 原文链接: https://arxiv.org/html/2603.20213

---
# AgenticGEO: A Self-Evolving Agentic System
for Generative Engine Optimization

Jiaqi Yuan School of Computer Science and Engineering, Beihang UniversityBeijingChina [yuanjq@buaa.edu.cn](2603.20213v1/mailto:yuanjq@buaa.edu.cn) , Jialu Wang Independent ContributorCA, United States [faldict@ucsc.edu](2603.20213v1/mailto:faldict@ucsc.edu) , Zihan Wang School of Computer Science and Engineering, Beihang UniversityBeijingChina [wzhan@buaa.edu.cn](2603.20213v1/mailto:wzhan@buaa.edu.cn) , Qingyun Sun School of Computer Science and Engineering, Beihang UniversityBeijingChina [sunqy@buaa.edu.cn](2603.20213v1/mailto:sunqy@buaa.edu.cn) , Ruijie Wang School of Computer Science and Engineering, Beihang UniversityBeijingChina [ruijiew@buaa.edu.cn](2603.20213v1/mailto:ruijiew@buaa.edu.cn) and Jianxin Li School of Computer Science and Engineering, Beihang UniversityBeijingChina [lijx@buaa.edu.cn](2603.20213v1/mailto:lijx@buaa.edu.cn)

(20 February 2007)

###### Abstract.

Generative search engines represent a transition from traditional ranking-based retrieval to Large Language Model (LLM)-based synthesis, transforming optimization goals from ranking prominence towards content inclusion. Generative Engine Optimization (GEO), specifically, aims to maximize visibility and attribution in black-box summarized outputs by strategically manipulating source content. However, existing methods rely on static heuristics, single-prompt optimization, or engine preference rule distillation that is prone to overfitting. They cannot flexibly adapt to diverse content or the changing behaviors of generative engines. Moreover, effectively optimizing these strategies requires an impractical amount of interaction feedback from the engines. To address these challenges, we propose AgenticGEO, a self-evolving agentic framework formulating optimization as a content-conditioned control problem, which enhances intrinsic content quality to robustly adapt to the unpredictable behaviors of black-box engines. Unlike fixed-strategy methods, AgenticGEO employs a MAP-Elites archive to evolve diverse, compositional strategies. To mitigate interaction costs, we introduce a Co-Evolving Critic, a lightweight surrogate that approximates engine feedback for content-specific strategy selection and refinement, efficiently guiding both evolutionary search and inference-time planning. Through extensive in-domain and cross-domain experiments on two representative engines, AgenticGEO  achieves state-of-the-art performance and demonstrates robust transferability, outperforming 14 baselines across 3 datasets. Our code and model are available at: [https://github.com/AIcling/agentic\_geo](https://github.com/AIcling/agentic_geo).

Generative Engine Optimization, Agentic Systems, Online Co-Evolution, Black-Box Optimization, Domain Generalization

††copyright: acmlicensed††journalyear: 2018††doi: XXXXXXX.XXXXXXX††conference: Make sure to enter the correct conference title from your rights confirmation email; June 03–05, 2018; Woodstock, NY††isbn: 978-1-4503-XXXX-X/2018/06††ccs: Computing methodologies Natural language processing††ccs: Information systems Information retrieval

## 1\. Introduction

_Generative search engines_ (e.g., Google AI Overviews (Stein, [2025](#bib.bib50); Cai, [2025](#bib.bib8)), Bing Search (Bing Search Blog, [2024](#bib.bib4)), Perplexity AI (Perplexity Support, [\[n. d.\]](#bib.bib41))) are increasingly dominant in information access, shifting users from browsing ranked webpages to consuming summarized answers directly provided by Large Language Models (LLMs). In contrast to traditional search engines that act as gateways to links, these systems retrieve evidence from multiple sources and compose it into a single, coherent summary, often accompanied by explicit citations (Gao et al., [2023](#bib.bib14); Menick et al., [2022](#bib.bib33); Nakano et al., [2021](#bib.bib35)). This paradigm shift fundamentally alters the web ecosystem, transforming the engine from a content ranker into a direct information summarizer.

This paper studies Generative Engine Optimization (GEO) (Aggarwal et al., [2024](#bib.bib2); Chen et al., [2025a](#bib.bib9)), which is an emerging optimization problem induced by this transition. While traditional Search Engine Optimization (SEO) (Shahzad et al., [2020](#bib.bib46); Almukhtar et al., [2021](#bib.bib3)) aims to maximize the position of a source content within a ranked list by optimizing retrieval signals (e.g., keywords and backlinks) (Saeed et al., [2024](#bib.bib44); Ziakis et al., [2019](#bib.bib65)), it is insufficient for modeling how LLMs synthesize and attribute evidence (Nestaas et al., [2024](#bib.bib37); Kumar and Lakkaraju, [2024](#bib.bib23)). In contrast, GEO targets two distinct objectives: (1) _Visibility_, the extent to which a source’s information is incorporated into the generated answer and (2) _Attribution_, whether and where the source is explicitly cited. GEO is critical for the sustainability of the web ecosystem, as generative answers increasingly govern the allocation of user attention (Brantner et al., [2025](#bib.bib5); Stein, [2025](#bib.bib50)).

![Refer to caption](2603.20213v1/x1.png)

Figure 1. Characterization of the GEO result on GEO-Bench instances. yy\-axis reports maximum performance among 9 rewriting strategies, and xx\-axis reports performance variance among strategies. (i) Optimization success varies greatly by strategy and content. (ii) Existing strategies fail to optimize nearly half of instances (points in gray and red areas), indicating static strategy pool is not enough and needs evolving. Details can be found in Appendix [A.1.1](#A1.SS1.SSS1 "A.1.1. Explanation of Figure1 ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization").

Despite the growing interest in GEO, the field still remains under-explored. As evidenced by the strategy sensitivity analysis (Figure [1](#S1.F1 "Figure 1 ‣ 1. Introduction ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")), optimization success varies greatly by strategy and content. Meanwhile, existing strategies fail to optimize nearly half of the samples. These findings indicate the need for both customized strategy selection for each piece of content and refining the static strategy pool so it can adapt to new content patterns. However, existing work fail to achieve the goal, where they can be broadly categorized into: static heuristics approaches (Aggarwal et al., [2024](#bib.bib2)) and learning-based approaches (Wu et al., [2025](#bib.bib55)). Static heuristic approaches apply heuristic rewriting strategies (i.e., rewriting prompt templates instructing an LLM) to source content. However, this paradigm overlooks the heterogeneity of content and apply single strategy for all cotents. Learning-based approaches, in contrast, adapt rewriting strategies to the behavior of a specific generative engine (GE). Although effective in controlled settings, they tend to overfit to engine-specific patterns and degrade when the engine updates. In a non-stationary black-box environment, where retrieval, synthesis, and citation behaviors evolve over time, a static strategy pool is suboptimal and prone to miscalibration. Moreover, learning-based methods depend on frequent and intensive feedback from the specific generative engine during training, which is costly and often infeasible in real-world systems. These limitations highlight two key challenges for GEO: _(i) Designing evolving methods that can flexibly adapt to diverse content and varying generative engine behaviors; (ii) Achieving effective optimization without relying on intensive feedback from generative engines._

![Refer to caption](2603.20213v1/x2.png)

Figure 2. GEO v.s. AgenticGEO. Static GEO methods apply fixed rewriting heuristics, whereas AgenticGEO maintains an evolving strategy archive and a critic to adaptively retrieve high-scoring strategies for iterative rewriting.

Motivated by these insights, we introduce AgenticGEO, a self-evolving agentic system that formulates GEO as learning a content-conditioned control policy, enhancing intrinsic quality for robust adaptation to black-box engines. As illustrated in Fig[2](#S1.F2 "Figure 2 ‣ 1. Introduction ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization"), instead of applying a fixed rewrite heuristic, AgenticGEO maintains an evolving _Quality-Diversity (QD) Archive_ as external memory, preserving high-performing yet diverse strategies. Each strategy represents a distinct way to rewrite content under different structural, stylistic, or semantic preferences. AgenticGEO further introduces a co-evolving critic to support agentic decision making. The critic serves as a surrogate evaluator and a planner. It identifies content-specific weaknesses, selects suitable strategies from the archive, and guides multi-step rewrites. By retrieving strategies from an evolved archive rather than relying on a fixed archive, AgenticGEO adapts naturally to diverse content and changing generative engine behaviors, addressing Challenge (i). To reduce reliance on intensive generative engine feedback, the critic is first calibrated using limited real feedback and then updated through continuous self-refinement. Once trained, it approximates generative engine preferences and provides stable guidance for strategy selection and rewrite execution. This design allows AgenticGEO to optimize visibility with substantially fewer feedback queries, addressing Challenge (ii). Our analysis suggests archive-driven co-evolution admits a sublinear regret bound O​(T)O(\\sqrt{T}). Empirically, AgenticGEO achieves the best optimization performance over 14 baselines on various benchmark datasets and generative engines (46.4%46.4\\% average gains. Moreover, AgenticGEO manages to preserve 98.1%98.1\\% performance using only 41.2%41.2\\% sparse GE feedback for optimization, indicating that the evolving critic substantially reduces supervision reliance.

Our contributions are summarized as follows:

-   •

    Content-conditioned GEO formulation: Notably, we are the first to formulate GEO as a _content-conditioned_ optimization problem under non-stationary black-box generative engines, where different contents can favor different rewriting strategies.

-   •

    Co-evolving strategy memory and surrogate critic: We propose an agentic system that co-evolves a Quality-Diversity (QD) strategy archive as external memory and a lightweight surrogate critic that guides online exploration and inference-time multi-turn planning, enabling continual adaptation.

-   •

    Strong effectiveness and transfer: Extensive experiments show consistent improvements over baselines in-domain and strong transfer to unseen domains. Further analyses provide convergence evidence, validate the necessity of core component, and confirm that the critic serves as a reliable proxy for the generative engine, reducing reliance on expensive GE feedback.


## 2\. Related Work

Generative Engine Optimization (GEO). Online content optimization has traditionally focused on Search Engine Optimization  (Shahzad et al., [2020](#bib.bib46); Almukhtar et al., [2021](#bib.bib3); Sharma et al., [2019](#bib.bib48); Lewandowski et al., [2021](#bib.bib25)), which improves a page’s position in ranked Search Engine Results Pages (SERPs) by optimizing for ranking factors. These factors typically combine retrieval-based relevance signals (Manning et al., [2008](#bib.bib32)) and link-analysis signals (e.g., PageRank (Brin and Page, [1998](#bib.bib6); Page et al., [1999](#bib.bib40))), together with classic on-page/off-page heuristics such as keywords, metadata, and backlinks (Saeed et al., [2024](#bib.bib44); Ziakis et al., [2019](#bib.bib65); Malaga, [2010](#bib.bib31)). With LLMs increasingly embedded into information access systems, user-facing search is shifting from ranked retrieval to retrieval-grounded answer synthesis in interactive, conversational settings (Lewis et al., [2020](#bib.bib26); Izacard and Grave, [2021](#bib.bib20); Nakano et al., [2022](#bib.bib36)).

In the era of generative search, Aggarwal et al. introduced Generative Engine Optimization and released GEO-Bench (Aggarwal et al., [2024](#bib.bib2)), reframing optimization as maximizing a source’s visibility within a generative engine’s synthesized response rather than competing for a rank position. They show that lightweight rewriting edits (e.g., adding authoritative citations, inserting statistics, and crafting quotable statements) can substantially increase a source’s inclusion in GE outputs. Building on this direction, AutoGEO (Wu et al., [2025](#bib.bib55)) distills engine preferences from LLM-generated explanations into rewriting rules, while RAID G-SEO (Chen et al., [2025b](#bib.bib10)) uses role-augmented intent inference and iterative reflection to guide intent-aligned rewriting.

Despite these advances, GEO remains in a developing stage. Most methods reduce GEO to LLM-based rewriting with fixed, hand-engineered prompts or static preference rules (Aggarwal et al., [2024](#bib.bib2); Wu et al., [2025](#bib.bib55); Chen et al., [2025b](#bib.bib10)), which lack adaptability under black-box, dynamic engines and are sensitive to prompt formatting (Sclar et al., [2024](#bib.bib45)). Moreover, a specific strategy’s effectiveness varies across domains and engines, yet existing methods rarely consider which rewriting strategy to apply based on the source content characteristics, limiting generalization and adaptation.

Self-Evolving Agentic Systems. Self-evolving agents operate as closed-loop optimizers over system inputs, architectures, and environmental feedback, emerging as a key paradigm (Hu et al., [2025](#bib.bib18); Fang et al., [2025](#bib.bib12); Li et al., [2025](#bib.bib27); Liu et al., [2025](#bib.bib29); Sun et al., [2023](#bib.bib51); Yao et al., [2022](#bib.bib57); Shinn et al., [2023](#bib.bib49); Madaan et al., [2023](#bib.bib30); Wang et al., [2023](#bib.bib53)). Existing systems are broadly organized as:

Policy Search. Early works reframe prompts as discrete, optimizable variables: APE (Zhou et al., [2022](#bib.bib64)) selects candidates via task-level scoring, while OPRO (Yang et al., [2023](#bib.bib56)) iteratively proposes instructions based on prior scores. However, these approaches often overfit to fixed protocols and lack online adaptivity. Recent methods focus on inference-time adaptation. Self-Refine (Madaan et al., [2023](#bib.bib30)) and Reflexion (Shinn et al., [2023](#bib.bib49)) iterate generation and feedback to revise solutions (Yuksel et al., [2025](#bib.bib58)). While effective for local errors, they typically follow fixed heuristic loops rather than learning to evolve, risking local optima when the generative engine updates.

Evolutionary Strategies. To mitigate local optima, population-based algorithms like EvoPrompt and Promptbreeder (Guo et al., [2023](#bib.bib16); Fernando et al., [2023](#bib.bib13)) evolve prompts via LLM-based mutations and fitness selection. Beyond prompts, recent systems extend this to agentic workflows (Zhang et al., [2024](#bib.bib60); Wang et al., [2025](#bib.bib54); Zhang et al., [2025b](#bib.bib63), [a](#bib.bib61); Zhai et al., [2025](#bib.bib59)). This suggests that GEO requires a self-evolving architecture that updates task understanding and planning from black-box engine feedback, which remains under-explored.

## 3\. Problem Formulation

Black-box GEO setting. We formulate Generative Engine Optimization as an optimization problem from the perspective of a content creator interacting with a black-box generative engine (GE), denoted as ℰ\\mathcal{E}. Given a user query q∈𝒬q\\in\\mathcal{Q}, the engine retrieves a candidate document set DqD\_{q} that includes the creator’s original content dd. A rewriting strategy s∈𝒮s\\in\\mathcal{S} is applied to a policy (e.g., an LLM) to produce an optimized version d~\\tilde{d}:

(1)

d~\=Rewrite​(d;s,q).\\tilde{d}=\\mathrm{Rewrite}(d;\\,s,q).

By substituting dd with d~\\tilde{d}, the updated candidate set D~q\=(Dq∖d)∪{d~}\\widetilde{D}\_{q}=(D\_{q}\\setminus d)\\cup\\{\\tilde{d}\\} is processed by ℰ\\mathcal{E} to generate a synthesized response 𝒜\\mathcal{A}.

Impression-based objective. The goal of the content creator is to identify an optimal strategy s∗∈Ss^{\\ast}\\in S that maximizes the visibility of the optimized content d~\\tilde{d} within the generated response 𝒜\\mathcal{A}. Let j⋆j^{\\star} denote the rank index of d~\\tilde{d} in D~\\widetilde{D}. Following the evaluation framework established in GEO-Bench (Aggarwal et al., [2024](#bib.bib2)), we quantify the visibility using impression metrics that measure the presence and prominence of d~\\tilde{d} in 𝒜\\mathcal{A}. The optimization objective is formulated as:

(2)

maxs∈𝒮⁡Scorej⋆​(q,s),\\max\_{s\\in\\mathcal{S}}\\ \\mathrm{Score}\_{j^{\\star}}(q,s),

where Scorej⋆​(⋅)\\mathrm{Score}\_{j^{\\star}}(\\cdot) represents a specific impression metric (e.g., word, pos, or overall impression; see Appendix [A.1.3](#A1.SS1.SSS3 "A.1.3. Impression metrics ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") for definitions).

## 4\. AgenticGEO Methodology

### 4.1. Overview

![Refer to caption](2603.20213v1/x3.png)

Figure 3. Overview of the AgenticGEO framework with two-stage training. Offline Alignment warm-starts a surrogate critic using offline preference pairs from the initial archive ℳ0\\mathcal{M}\_{0}, calibrating it for fast, content-conditioned strategy scoring. Online Co-Evolution then interacts with the black-box Generative Engine (GE) to iteratively, simultaneously evolve a MAP-Elites quality-diversity archive and the critic. Parent strategies are mutated by a learned evolver trained with sibling-aware AWR, the critic screens candidates to reduce GE calls, and newly collected GE feedback is stored in a replay buffer to continually recalibrate the critic and update the archive through a value-novelty gate. At inference time, the evolved archive and critic enable agentic multi-turn rewriting by selecting and executing a content-adaptive plan of strategies.

As Figure [3](#S4.F3 "Figure 3 ‣ 4.1. Overview ‣ 4. AgenticGEO Methodology ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") shows, AgenticGEO proceeds in three stages:

-   •

    Offline Critic Alignment: We warm-start a lightweight surrogate _critic_ using offline preference pairs from the training dataset to approximate GE feedback, without costly online evaluations.

-   •

    Online Co-Evolution: Through a co-evolutionary loop, we jointly train the MAP-Elites strategy archive and the critic module with the real GE interactions.

-   •

    Agentic Multi-Turn Rewriting: At inference time, we perform agentic multi-step planning, where the critic orchestrates strategy selection, while the rewriter operates the chosen strategies to optimize content.


### 4.2. Offline Critic Preference Alignment

To avoid the high latency of online interactions with the black-box engine, we train a lightweight _critic_ to serve as a surrogate evaluator. This critic is aligned with offline engine feedback to learn strategy-conditioned preferences, enabling an efficient warm-start.

Setup & Notation. Given a query qq, a document dd, and a rewriting strategy s∈ℳ0s\\in\\mathcal{M}\_{0} (see Appendix [A.1.4](#A1.SS1.SSS4 "A.1.4. Seed Strategies ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")), we denote the input context as x\=(q,d)x=(q,d). Each strategy ss is instantiated as a textual prompt template that instructs an LLM to rewrite source content dd.

Architecture & Context Encoding. We implement the critic using a _backbone + value head_ structure, denoted by 𝒞\\mathcal{C}. We select a lightweight decoder-only Language Model (LM) as the backbone to leverage its inherent semantic reasoning capabilities, which are essential for capturing the complex dependencies between optimization strategies and the query-content context.

Given context xx and strategy ss, the backbone encodes their concatenation into a latent representation h​(x,s)h(x,s), which is projected by a two-layer MLP value head to a numerical score:

(3)

h​(x,s)\=LM​(\[x;s\]),𝒞​(x,s)\=MLP​(h​(x,s)),h(x,s)=\\mathrm{LM}\\!\\left(\[x;s\]\\right),\\qquad\\mathcal{C}(x,s)=\\mathrm{MLP}\\!\\Big(h(x,s)\\Big),

where 𝒞​(x,s)\\mathcal{C}(x,s) is expected to predict the impression gain induced by applying strategy ss to context xx before feeding it into GE.

Offline Supervision Data Construction. We construct offline supervision from the seed strategy pool ℳ0\\mathcal{M}\_{0} (illustrated at Appendix [A.1.4](#A1.SS1.SSS4 "A.1.4. Seed Strategies ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")). For each context xx and strategy ss, we define the supervised gain as the improvement over the unrewritten baseline:

(4)

rsup​(x,s)\=Score​(𝒜strain)−Score​(𝒜0train),r^{\\text{sup}}(x,s)=\\mathrm{Score}\\!\\left(\\mathcal{A}^{\\text{train}}\_{s}\\right)-\\mathrm{Score}\\!\\left(\\mathcal{A}^{\\text{train}}\_{0}\\right),

where 𝒜strain\\mathcal{A}^{\\text{train}}\_{s} denotes the generative engine output after applying strategy ss to xx, and 𝒜0train\\mathcal{A}^{\\text{train}}\_{0} is the corresponding unrewritten baseline output. Score​(⋅)\\mathrm{Score}(\\cdot) is the overall impression metric defined in Appendix [A.1.3](#A1.SS1.SSS3 "A.1.3. Impression metrics ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization"), combining Word and Pos. We use rsup​(x,s)r^{\\text{sup}}(x,s) as the offline alignment target for the critic output 𝒞​(x,s)\\mathcal{C}(x,s).

Hybrid Objective. Effective preference alignment requires capturing both the _absolute value_ and the _relative order_ of strategies. We propose a hybrid objective combining regression and ranking:

(5)

ℒtotal\=ℒpair+λ​ℒreg.\\mathcal{L}\_{\\text{total}}=\\mathcal{L}\_{\\text{pair}}+\\lambda\\mathcal{L}\_{\\text{reg}}.

(1) Score Regression: We use the Huber loss (Huber, [1992](#bib.bib19)) to regress 𝒞​(x,s)\\mathcal{C}(x,s) onto rsup​(x,s)r^{\\text{sup}}(x,s), which is less sensitive to noisy supervision:

(6)

ℒreg\=𝔼(x,s)​\[Huber​(𝒞​(x,s),rsup​(x,s))\].\\mathcal{L}\_{\\text{reg}}=\\mathbb{E}\_{(x,s)}\\Big\[\\textsc{Huber}\\big(\\mathcal{C}(x,s),\\,r^{\\text{sup}}(x,s)\\big)\\Big\].

(2) Rank-Aware Pairwise Alignment: While regression calibrates the value scale, downstream strategy selection primarily depends on relative ordering. We therefore construct pairwise strategy preferences within the same context: for each xx, we rank strategies in ℳ0\\mathcal{M}\_{0} by rsup​(x,s)r^{\\text{sup}}(x,s) (rank 11 is best), and sample ordered pairs (s+,s−)(s^{+},s^{-}) such that rsup​(x,s+)\>rsup​(x,s−)r^{\\text{sup}}(x,s^{+})>r^{\\text{sup}}(x,s^{-}). Since accurate discrimination among top strategies is most important for strategy selection, we assign larger weights to pairs involving higher-ranked strategies:

(7)

w​(s+,s−)\=1rankx​(s+)+rankx​(s−).w(s^{+},s^{-})=\\frac{1}{\\text{rank}\_{x}(s^{+})+\\text{rank}\_{x}(s^{-})}.

The weighted pairwise loss emphasizes the most promising strategies for reliable selection:

(8)

ℒpair\=𝔼(x,s+,s−)​\[w​(s+,s−)⋅log⁡(1+e−(𝒞​(x,s+)−𝒞​(x,s−)))\].\\hskip-8.61108pt\\mathcal{L}\_{\\text{pair}}=\\mathbb{E}\_{(x,s^{+},s^{-})}\\!\\left\[w(s^{+},s^{-})\\cdot\\log\\!\\Big(1+e^{-(\\mathcal{C}(x,s^{+})-\\mathcal{C}(x,s^{-}))}\\Big)\\right\].

Staged Training Strategy. To further stabilize alignment, we employ a two-phase process. We primarily sample _Top-55 dense pairs_ to refine fine-grained local ordering, and _global contrastive pairs_ to ensure coarse separation. We initially freeze the backbone to warm up the value head, preventing representation collapse, before unfreezing all parameters for joint fine-tuning.

### 4.3. Online Strategy-Critic Co-Evolution

While offline alignment initializes the system, relying on static strategies risks local optima and fails to adapt to dynamic search environments. To enable continuous adaptation, we introduce an _Online Strategy–Critic Co-Evolution_ framework. This establishes a self-evolving loop where the _Evolver_ (EE), a parameterized LLM that generates strategy mutations, actively expands the strategy space to discover novel ones, while the _Critic_ (𝒞\\mathcal{C}) continuously recalibrates to guide exploration and enable optimal strategy selection at inference.

Table 1. Structure of the evolving strategy representation. Each dimension is mutated independently. It can be rendered into a compact summary for critic scoring and a full strategy prompt for rewriting (see Appendix [A.1.5](#A1.SS1.SSS5 "A.1.5. Genotype Details ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")).

Dimension

Semantics & Examples

Instruction

Defines goal and scope (e.g., target audience, core facts, key emphasis, expert role).

Constraints

Sets strict boundaries (e.g., word count, citation checks, anti-hallucination, fact consistency).

Reasoning

Adds logic steps (e.g., conflict resolution, self-correction, step planning, logic verification).

Format

Controls output layout (e.g., bullet lists, code blocks, output schema, section preludes).

Tone

Adjusts writing style (e.g., assertive voice, technicality, simple language, formality level).

#### 4.3.1. Structured Evolution via MAP-Elites Archive

To prevent the optimizer from collapsing into a single “safe” pattern (e.g., always using an authoritative tone) that fails on diverse content, we maintain a dynamic _MAP-Elites Archive_ ℳ\\mathcal{M} (Mouret and Clune, [2015](#bib.bib34); Pugh et al., [2016](#bib.bib42); Justesen et al., [2019](#bib.bib22)). Instead of seeking one global optimum, this archive acts as an evolving memory that preserves a wide range of high-performing strategies.

Unlike a standard top-kk list that discards lower-scoring but distinct solutions, ℳ\\mathcal{M} organizes strategies into a multi-dimensional grid of _behavioral cells_. Each cell represents a specific combination of attributes (see Table [1](#S4.T1 "Table 1 ‣ 4.3. Online Strategy-Critic Co-Evolution ‣ 4. AgenticGEO Methodology ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")), such as an Assertive tone combined with a List format, ensuring that unique strategy styles compete only against similar ones. A new strategy ss captures a cell only if it triggers the _Value-Novelty Gate_ (details in Appendix [A.1.6](#A1.SS1.SSS6 "A.1.6. MAP-Elites Descriptors and Archive Gates ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")):

1.  (1)

    Value: It achieves a higher impression score from the Generative Engine than the current elite in that cell;

2.  (2)

    Novelty: It is structurally distinct from existing entries (measured by nn\-gram distance (Broder, [1997](#bib.bib7))), expanding the archive’s coverage even if its score is currently lower.


To manage archive capacity and support evolution exploration, we assign each retained strategy a composite _PND Score_ (Pareto-Novelty-Diversity) (Lehman and Stanley, [2011](#bib.bib24); Deb et al., [2002](#bib.bib11)):

(9)

SPND​(s)\=r​(s)+λpnd⋅(Nov⁡(s)+Div⁡(s)),S\_{\\mathrm{PND}}(s)=r(s)+\\lambda\_{\\mathrm{pnd}}\\cdot\\big(\\operatorname{Nov}(s)+\\operatorname{Div}(s)\\big),

where r​(s)r(s) is the impression score from the critic or generative engine, and Nov⁡(s)\\operatorname{Nov}(s) and Div⁡(s)\\operatorname{Div}(s) measure structural uniqueness and lineage diversity (see Appendix [A.1.7](#A1.SS1.SSS7 "A.1.7. PND Score Formulation and Pruning ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")). This score serves two roles: _Global Pruning_ to discard redundant strategies when the archive is full, and a _dense intrinsic reward_ for the Evolver (Eq. [10](#S4.E10 "In 4.3.3. Evolver Optimization via Sibling-Aware AWR ‣ 4.3. Online Strategy-Critic Co-Evolution ‣ 4. AgenticGEO Methodology ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")) to encourage exploration beyond pure exploitation.

Algorithm 1 Archive-Driven Strategy-Critic Co-Evolution

1:Initial archive ℳ0\\mathcal{M}\_{0}; data distribution 𝒟\\mathcal{D} over content; evolver EE; critic 𝒞\\mathcal{C}; generative engine GE\\mathrm{GE}; online iterations TT; exploit size KtopK\_{\\text{top}}; explore size KrandK\_{\\text{rand}}.

2:ℳ←ℳ0\\mathcal{M}\\leftarrow\\mathcal{M}\_{0}

3:Initialize replay buffers ℬtrue←∅,ℬpred←∅\\mathcal{B}\_{\\text{true}}\\leftarrow\\emptyset,\\ \\mathcal{B}\_{\\text{pred}}\\leftarrow\\emptyset

4:for t\=1,…,Tt=1,\\dots,T do

5:  x∼𝒟x\\sim\\mathcal{D} ⊳\\triangleright e.g., (q,d)(q,d)

6:  Phase 1: Hybrid Candidate Generation

7:  P←Sample​(ℳt)P\\leftarrow\\mathrm{Sample}(\\mathcal{M}\_{t})

8:  Sevolver←{s∣s∼E(⋅∣sp),sp∈P}S\_{\\text{evolver}}\\leftarrow\\{\\,s\\mid s\\sim E(\\cdot\\mid s\_{p}),\\ s\_{p}\\in P\\,\\} ⊳\\triangleright neural mutation

9:  Sops←{Mutate​(sp)∣sp∈P}S\_{\\text{ops}}\\leftarrow\\{\\,\\mathrm{Mutate}(s\_{p})\\mid s\_{p}\\in P\\,\\} ⊳\\triangleright symbolic perturbation

10:  Scand←Sevolver∪SopsS\_{\\text{cand}}\\leftarrow S\_{\\text{evolver}}\\cup S\_{\\text{ops}}

11:  Phase 2: Critic Scoring & Budgeted Selection

12:  Rcritic​(s)←𝒞​(x,s),∀s∈ScandR\_{\\text{critic}}(s)\\leftarrow\\mathcal{C}(x,s),\\ \\forall s\\in S\_{\\text{cand}}

13:  Seval←TopK​(Scand,Rcritic,Ktop)∪Random​(Scand,Krand)S\_{\\text{eval}}\\leftarrow\\mathrm{TopK}(S\_{\\text{cand}},R\_{\\text{critic}},K\_{\\text{top}})\\ \\cup\\ \\mathrm{Random}(S\_{\\text{cand}},K\_{\\text{rand}})

14:  Phase 3: GE Evaluation & Joint Reward Aggregation

15:  Rtrue​(s)←GE​(x,s),∀s∈SevalR\_{\\text{true}}(s)\\leftarrow\\mathrm{GE}(x,s),\\ \\forall s\\in S\_{\\text{eval}}

16:  Rmix​(s)←{Rtrue​(s),s∈Seval,Rcritic​(s),s∈Scand∖Seval.R\_{\\text{mix}}(s)\\leftarrow\\begin{cases}R\_{\\text{true}}(s),&s\\in S\_{\\text{eval}},\\\\ R\_{\\text{critic}}(s),&s\\in S\_{\\text{cand}}\\setminus S\_{\\text{eval}}.\\end{cases}

17:  ℳt+1←UpdateArchive​(ℳt,Scand,Rmix)\\mathcal{M}\_{t+1}\\leftarrow\\mathrm{UpdateArchive}(\\mathcal{M}\_{t},S\_{\\text{cand}},R\_{\\text{mix}})

18:  ℬtrue←ℬtrue∪{(x,s,Rtrue​(s))∣s∈Seval}\\mathcal{B}\_{\\text{true}}\\leftarrow\\mathcal{B}\_{\\text{true}}\\cup\\{(x,s,R\_{\\text{true}}(s))\\mid s\\in S\_{\\text{eval}}\\}

19:  ℬpred←ℬpred∪{(x,s,Rmix​(s))∣s∈Scand∖Seval}\\mathcal{B}\_{\\text{pred}}\\leftarrow\\mathcal{B}\_{\\text{pred}}\\cup\\{(x,s,R\_{\\text{mix}}(s))\\mid s\\in S\_{\\text{cand}}\\setminus S\_{\\text{eval}}\\}

20:  Phase 4: Online Updates

21:  Et+1←TrainEvolver​(Et,ℬtrue∪ℬpred)E\_{t+1}\\leftarrow\\mathrm{TrainEvolver}(E\_{t},\\mathcal{B}\_{\\text{true}}\\cup\\mathcal{B}\_{\\text{pred}})

22:  𝒞t+1←TrainCritic​(𝒞t,ℬtrue)\\mathcal{C}\_{t+1}\\leftarrow\\mathrm{TrainCritic}(\\mathcal{C}\_{t},\\mathcal{B}\_{\\text{true}})

23:end for

24:return Evolved archive ℳ\\mathcal{M}, evolved critic 𝒞\\mathcal{C}

#### 4.3.2. The Co-Evolutionary Loop

With the diverse population anchored by the Archive, the online process drives a _co-evolutionary loop_ where the Evolver and Critic mutually refine their capabilities through four phases per iteration (shown in Algorithm [1](#alg1 "Algorithm 1 ‣ 4.3.1. Structured Evolution via MAP-Elites Archive ‣ 4.3. Online Strategy-Critic Co-Evolution ‣ 4. AgenticGEO Methodology ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")):

1.  1.

    Generation: Parents sampled from ℳ\\mathcal{M} undergo hybrid mutation. The evolver EE selects an operator from our predefined catalog and generates the resulting child\_genotype (e.g., applying mut\_F\_schema\_swap to change the output format), while symbolic Operators inject hard perturbations via field-level mutations (e.g., mut\_T\_toggle\_tone for style switching, or mut\_C\_st- rengthen for constraint injection). Details in Appendix [A.1.8](#A1.SS1.SSS8 "A.1.8. Evolver Action Space and Prompting ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization").

2.  2.

    Screening: To reduce computational cost, the _Critic_ 𝒞\\mathcal{C} filters candidates, selecting the Top-KtopK\_{\\text{top}} strategies for exploitation and a random KrandK\_{\\text{rand}} subset for exploration to mitigate selection bias.

3.  3.

    Evaluation: The Generative Engine evaluates the selected candidates. The resulting GE feedback, together with the critic scores for the remaining candidates, is merged into a joint reward signal to update the archive via the Value-Novelty gate, and all experiences are logged into the replay buffers ℬtrue\\mathcal{B}\_{\\text{true}} and ℬpred\\mathcal{B}\_{\\text{pred}} for subsequent online updates.

4.  4.

    Learning: The replay buffers drive online updates of the evolver EE and recalibration of the critic CC. EE is trained on both ℬtrue\\mathcal{B}\_{\\text{true}} and ℬpred\\mathcal{B}\_{\\text{pred}}, while CC is updated only with GE-labeled samples in ℬtrue\\mathcal{B}\_{\\text{true}}, enabling continual adaptation as the strategy population evolves.


#### 4.3.3. Evolver Optimization via Sibling-Aware AWR

The Evolver EE synthesizes a candidate strategy snews\_{\\text{new}} from a parent sps\_{p} (or a parent pair) by selecting optimal mutation or crossover operators. A naive Reinforcement Learning approach is unstable due to the high variance of impression scores from the Generative Engine. We instead employ _Advantage-Weighted Regression (AWR)_.

Inspired by GRPO-style relative advantage calculation (Shao et al., [2024](#bib.bib47)), we further stabilize learning under noisy feedback. Crucially, to mitigate noise across heterogeneous content contexts (where some source material is inherently harder to optimize), we propose a _Sibling-Aware Advantage_. Instead of comparing rewards globally, we compare a candidate’s performance relative to its “siblings” generated from the same parent strategy:

(10)

Ai\=(ri−rparent)⏟Absolute Gain−αsib⋅mean⁡({Δj}j∈siblings)+𝕀​(Δi<0)⋅SPND​(si),A\_{i}=\\underbrace{(r\_{i}-r\_{\\mathrm{parent}})}\_{\\text{Absolute Gain}}-\\alpha\_{\\mathrm{sib}}\\cdot\\operatorname{mean}\\!\\left(\\{\\Delta\_{j}\\}\_{j\\in\\mathrm{siblings}}\\right)+\\mathbb{I}(\\Delta\_{i}<0)\\cdot S\_{\\mathrm{PND}}(s\_{i}),

where rr denotes the score from the critic and generative engine, Δi\=ri−rparent\\Delta\_{i}=r\_{i}-r\_{\\mathrm{parent}}, and SPND​(si)S\_{\\mathrm{PND}}(s\_{i}) is the exploration bonus (Eq. [22](#A1.E22 "In A.1.7. PND Score Formulation and Pruning ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")). The sibling mean provides a within-parent baseline, so AiA\_{i} better reflects the effect of the chosen evolution operator rather than the intrinsic difficulty of the content. The last term adds an exploration bonus when the immediate gain is non-positive, helping retain novel and diverse strategies. The policy is then updated to imitate these high-advantage actions through weighted supervised fine-tuning (SFT) (Ouyang et al., [2022](#bib.bib39)), minimizing the following loss:

(11)

ℒEvolver\=−𝔼(x,s)∼(ℬtrue∪ℬpred)​\[exp⁡(A​(x,s)β)⋅log⁡E​(s|x)\].\\mathcal{L}\_{\\mathrm{Evolver}}=-\\mathbb{E}\_{(x,s)\\sim(\\mathcal{B}\_{\\mathrm{true}}\\cup\\mathcal{B}\_{\\mathrm{pred}})}\\left\[\\exp\\left(\\frac{A(x,s)}{\\beta}\\right)\\cdot\\log E(s|x)\\right\].

#### 4.3.4. Online Critic Calibration

Complementing the Evolver updates, we continuously recalibrate the critic 𝒞\\mathcal{C} using new labeled triplets (x,s,r)(x,s,r) collected in the replay buffer ℬtrue\\mathcal{B}\_{\\mathrm{true}}. By optimizing the hybrid objective in Eq. [5](#S4.E5 "In 4.2. Offline Critic Preference Alignment ‣ 4. AgenticGEO Methodology ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization"), we keep the critic calibrated under the evolving archive and feedback distribution, enabling reliable scoring for online selection and inference-time agentic planning.

### 4.4. Theoretical analysis.

Let ℛ​(s)\\mathcal{R}(s) denote the risk induced by the strategy ss. The regret of the proposed critic-evolver co-evolutionary algorithm is analyzed in Theorem [4.1](#S4.Thmtheorem1 "Theorem 4.1 (Informal). ‣ 4.4. Theoretical analysis. ‣ 4. AgenticGEO Methodology ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization").

###### Theorem 4.1 (Informal).

Under the conditions of a linearly growing replay buffer and a Lipschitz-continuous critic, the AgenticGEO framework achieves a cumulative regret:

∑t\=1Tℛ​(st)−ℛ​(s∗)\=𝒪​(T).\\sum\_{t=1}^{T}\\mathcal{R}(s\_{t})-\\mathcal{R}(s^{\*})=\\mathcal{O}(\\sqrt{T}).

###### Proof Sketch.

We first decompose the instantaneous risk gap at each time step tt as

ℛ​(st)−ℛ​(s∗)≤|ℛ​(st)−𝒞t​(st)|+|𝒞t​(st)−𝒞t​(s∗)|+|𝒞t​(s∗)−ℛ​(s∗)|.\\mathcal{R}(s\_{t})-\\mathcal{R}(s^{\\ast})\\leq|\\mathcal{R}(s\_{t})-\\mathcal{C}\_{t}(s\_{t})|+|\\mathcal{C}\_{t}(s\_{t})-\\mathcal{C}\_{t}(s^{\\ast})|+|\\mathcal{C}\_{t}(s^{\\ast})-\\mathcal{R}(s^{\\ast})|.

Given a replay buffer that grows linearly, the approximation and generalization errors of the critic model satisfy |ℛ​(s)−𝒞t​(s)|\=𝒪​(1t).|\\mathcal{R}(s)-\\mathcal{C}\_{t}(s)|=\\mathcal{O}(\\frac{1}{\\sqrt{t}}). The evolver’s selection process follows standard online learning bound by |𝒞t​(st)−𝒞t​(s∗)|\=𝒪​(1t).|\\mathcal{C}\_{t}(s\_{t})-\\mathcal{C}\_{t}(s^{\\ast})|=\\mathcal{O}(\\frac{1}{\\sqrt{t}}). Combining above and summing over the time horizon TT, we can conclude that the cumulative regret is

∑t\=1Tℛ​(st)−ℛ​(s∗)\=∑t\=1T𝒪​(1t)\=𝒪​(T).\\sum\_{t=1}^{T}\\mathcal{R}(s\_{t})-\\mathcal{R}(s^{\\ast})=\\sum\_{t=1}^{T}\\mathcal{O}(\\frac{1}{\\sqrt{t}})=\\mathcal{O}(\\sqrt{T}).

∎

This implies that as the number of iterations TT increases, the average performance gap vanishes, guaranteeing that the system asymptotically converges to the optimal strategy. More detailed theoretical analysis and the proofs are provided in Appendix [A.3](#A1.SS3 "A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization").

### 4.5. Agentic Multi-Turn Rewriting with Critic-Guided Planning

The inference phase deploys the evolved archive ℳ\\mathcal{M} and critic 𝒞\\mathcal{C} for multi-turn optimization. We formulate this as a content-conditioned decision-making process, where the critic serves as a fast proxy planner. This allows the agent to guide a greedy search over the strategy space, enabling rapid evaluation while avoiding expensive black-box interactions.

At each step τ\\tau (initialized with d0\=dd\_{0}=d), the agent plans the next optimal move by selecting a strategy sτ∗s\_{\\tau}^{\*} that maximizes the critic’s predicted potential, while enforcing a Tabu List 𝒯τ\\mathcal{T}\_{\\tau} (recording previously utilized strategies) to prevent repeated operations:

(12)

sτ∗\=arg​maxs∈ℳ∖𝒯τ⁡𝒞​((q,dτ),s).s\_{\\tau}^{\*}=\\operatorname\*{arg\\,max}\_{s\\in\\mathcal{M}\\setminus\\mathcal{T}\_{\\tau}}\\;\\mathcal{C}\\big((q,d\_{\\tau}),s\\big).

Subsequently, the content state transitions via the rewriting tool, and the utilized strategy is recorded to update the constraint set:

(13)

dτ+1\=Rewrite⁡(dτ,sτ∗,q),𝒯τ+1←𝒯τ∪{sτ∗}.d\_{\\tau+1}=\\operatorname{Rewrite}(d\_{\\tau},s\_{\\tau}^{\*},q),\\quad\\mathcal{T}\_{\\tau+1}\\leftarrow\\mathcal{T}\_{\\tau}\\cup\\{s\_{\\tau}^{\*}\\}.

The loop terminates when the marginal gain vanishes:

(14)

maxs∈ℳ∖𝒯τ+1⁡𝒞​((q,dτ+1),s)≤maxs∈ℳ∖𝒯τ⁡𝒞​((q,dτ),s),\\max\_{s\\in\\mathcal{M}\\setminus\\mathcal{T}\_{\\tau+1}}\\mathcal{C}\\big((q,d\_{\\tau+1}),s\\big)\\leq\\max\_{s\\in\\mathcal{M}\\setminus\\mathcal{T}\_{\\tau}}\\mathcal{C}\\big((q,d\_{\\tau}),s\\big),

or steps exceed Tm​a​xT\_{max}. This agentic planning capability allows AgenticGEO to dynamically adapt its optimization path based on the evolving characteristics of the content, yielding a highly optimized content that occupies a more prominent role within the engine’s information synthesis and attribution.

## 5\. Experiments

We empirically validate the effectiveness and generalization ability of AgenticGEO. We study the following research questions:

1.  RQ1

    Overall Performance & Robustness: How does AgenticGEO compare to state-of-the-art methods, and is its performance robust to generative engines varying in architecture and scale?

2.  RQ2

    Transferability to Unseen Domains: Can an optimization policy maintain performance when deployed on out-of-distribution domains?

3.  RQ3

    Ablation and Hyperparameters Analysis: How does each co-evolutionary component influence the performance? Specifically, does the pre-trained critic provide a reliable warm-start?

4.  RQ4

    Semantic Consistency: Does the optimization maintain the original meaning of the content, ensuring that visibility gains do not come at the cost of information loss?


### 5.1. Exprimental Setup

We briefly introduce the experimental setup.

-   •

    Dataset. GEO-Bench (Aggarwal et al., [2024](#bib.bib2)) serves as our training dataset, derived from Google Search results spanning a wide spectrum of domains and query difficulties. To assess zero-shot generalization to unseen distributions, we employ MS MARCO (Nguyen et al., [2016](#bib.bib38)), comprising short-text passages from real-world Bing search logs, and a custom E-commerce (Reddy et al., [2022](#bib.bib43)) sourced from Amazon, representing a specific vertical for product search. Details are in Appendix [A.2.1](#A1.SS2.SSS1 "A.2.1. Dataset. ‣ A.2. Experiment Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")

-   •

    Settings. To conduct a comprehensive evaluation, we use GEO-Bench (Aggarwal et al., [2024](#bib.bib2)) training dataset for evolving the archive and critic, and extend the assessment to MS-Marco (Nguyen et al., [2016](#bib.bib38)) and E-commerce (Reddy et al., [2022](#bib.bib43)) datasets. This diverse benchmark allows us to examine the performance consistency across varying content distributions and verify its broad applicability in real-world scenarios.

-   •

    Baselines. We group baselines into two categories: Static heuristics apply fixed rewriting heuristics: No optimization, Keyword Stuffing, Unique Words, Easy-To-Understand, Authoritative, Technical Words, Fluency Optimization, Cite Sources, Quotation Addition, Statistics Addition. Learning-based methods train models to generate optimized rewrites: AutoGEO, Cite Sources-SFT, Quotation Addition-SFT, Statistics Addition-SFT. Details are deferred to Appendix [A.2.2](#A1.SS2.SSS2 "A.2.2. Baselines. ‣ A.2. Experiment Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization").

-   •

    Models & Metrics. We employ Qwen2.5-32B-Instruct and Llama-3.3-70B-Instruct as downstream generative engines (Team, [2025](#bib.bib52); Grattafiori et al., [2024](#bib.bib15)). For system components, we implement the Critic backbone with Qwen2.5-1.5B, the Evolver with Qwen2.5-7B-Instruct, and the Rewriter with Qwen2.5-32B-Instruct for tool invocation. We measure performance via Attributed Word Count, Position-Weighted Citation Order, and their Combination as overall. (Aggarwal et al., [2024](#bib.bib2)) (Definition in Appendix [A.1.3](#A1.SS1.SSS3 "A.1.3. Impression metrics ‣ A.1. Methodological Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization").)

-   •

    Implementation. We employ LoRA (Hu et al., [2022](#bib.bib17)) to fine-tune both the Critic and Evolver for 2 epochs. All experiments are implemented on 4 NVIDIA RTX Pro 6000 GPUs. At inference time, we select the top-2525 strategies from the evolved archive ranked by their SPNDS\_{\\mathrm{PND}} scores, and perform critic-guided multi-turn rewriting with a maximum of 33 rewrite steps. Other details in Appendix [A.2](#A1.SS2 "A.2. Experiment Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization").


### 5.2. Overall Performance and Robustness (RQ1).

Table [2](#S5.T2 "Table 2 ‣ 5.2. Overall Performance and Robustness (RQ1). ‣ 5. Experiments ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") presents the comparative results of AgenticGEO against all baselines on the in-domain GEO-Bench dataset. We observe that AgenticGEO consistently achieves state-of-the-art performance on two generative engines, demonstrating strong effectiveness and robustness against engine variations in architecture and scale.

On the Qwen2.5-32B-Instruct engine, AgenticGEO achieves an Overall score of 25.48, surpassing the strongest baseline (AutoGEO) which scores 23.71. This represents a substantial improvement over static heuristic strategies, such as Keyword Stuffing (20.69) and Authoritative (20.60), confirming that fixed rewriting rules are insufficient for the dynamic nature of generative engines. Furthermore, our method outperforms the Supervised Fine-Tuning (SFT) baselines. This performance improvement indicates that our self-evolving strategy archive effectively transcends the optimization upper bound imposed by static strategies’ supervision, capturing content-centric patterns that are ignored by existing methods.

AgenticGEO also demonstrates strong robustness on the larger Llama-3.3-70B-Instruct engine. While many baselines struggle to transfer their gains (e.g., Statistics Addition drops to 21.05), AgenticGEO maintains a strongest performance with Overall of 24.52. This consistency across different model architectures and scales validates that our co-evolving critic and strategy archive learn generalized optimization principles rather than overfitting to a specific engine, presenting the necessity of keeping strategy diverse.

Table 2. Overall Performance on the in-domain setting. Average results on 55 independent runs are reported. ∗\* indicates the statistically significant improvements over the best baseline, with pp\-value smaller than 0.0010.001.

Methods

GEO-Bench

Qwen2.5-32B-Instruct

Llama3.3-70B-Instruct

word

pos

overall

word

pos

overall

No optimization

20.05

20.26

20.21

19.19

19.33

19.20

Keyword Stuffing

20.73

20.86

20.69

19.99

20.16

20.02

Unique Words

17.59

17.94

17.78

16.78

16.66

16.56

Easy-To-Understand

20.10

20.19

20.05

18.72

18.93

18.85

Authoritative

20.41

20.93

20.60

19.41

19.48

19.47

Technical Words

21.22

20.97

21.23

19.55

19.59

19.50

Fluency Optimization

20.66

20.85

20.73

19.31

19.58

19.47

Cite Sources

22.64

22.91

22.53

21.95

22.11

21.98

Quotation Addition

23.96

24.18

23.76

21.74

21.77

21.57

Statistics Addition

22.34

22.86

22.30

21.07

21.23

21.05

AutoGEO

23.51

23.70

23.71

22.77

22.65

22.78

Cite Sources-SFT

23.02

23.30

22.91

22.26

22.43

22.21

Quotation Addition-SFT

24.10

24.28

23.92

22.31

22.45

22.20

Statistics Addition-SFT

23.05

23.47

23.02

21.79

21.90

21.75

AgenticGEO (ours)\*

25.42

25.85

25.48

24.38

24.59

24.52

Gains (%\\%)

26.78

27.59

26.08

27.05

27.21

27.71

Table 3. Overall Performance on the cross-domain setting. Average results on 55 independent runs are reported. ∗\* indicates the statistically significant improvements over the best baseline, with pp\-value smaller than 0.0010.001.

Qwen2.5-32B-Instruct

Llama3.3-70B-Instruct

Methods

MS MARCO

E-Commerce

MS MARCO

E-Commerce

word

pos

overall

word

pos

overall

word

pos

overall

word

pos

overall

No optimization

19.99

20.15

20.05

18.30

18.09

18.01

19.45

19.64

19.67

19.70

19.45

19.68

Keyword Stuffing

23.26

22.63

22.75

18.94

18.52

18.65

22.02

21.77

21.96

20.24

19.96

20.16

Unique Words

17.95

18.24

18.23

18.12

18.09

18.01

18.94

18.88

18.76

19.16

19.04

19.15

Easy-To-Understand

20.48

20.46

20.46

20.46

20.45

20.29

19.75

19.84

19.84

20.28

19.91

20.18

Authoritative

21.29

21.08

21.07

19.84

19.32

19.64

20.23

20.21

20.10

20.06

19.82

20.06

Technical Words

22.20

22.15

22.27

20.58

20.68

20.34

21.59

21.51

21.58

20.53

20.22

20.48

Fluency Optimization

19.59

19.20

19.41

20.25

20.06

20.11

20.99

20.95

20.97

19.75

19.54

19.68

Cite Sources

27.65

26.47

26.54

21.28

21.06

21.54

25.36

24.71

24.97

21.69

21.31

21.52

Quotation Addition

29.70

28.70

28.43

21.75

21.91

21.54

26.59

25.81

25.66

20.85

20.49

20.69

Statistics Addition

25.79

24.89

24.91

20.64

20.15

20.43

23.69

23.17

23.33

20.29

20.07

20.28

AutoGEO

31.79

31.14

30.67

21.54

19.75

21.18

30.27

29.11

30.04

21.45

20.13

21.50

Cite Sources-SFT

30.24

29.55

29.36

21.96

21.88

21.67

28.63

28.07

28.15

21.70

21.43

21.65

Quotation Addition-SFT

31.16

30.30

30.08

22.14

21.96

21.83

29.57

28.91

28.96

21.91

21.66

21.70

Statistics Addition-SFT

29.21

28.75

28.34

21.83

21.49

21.60

27.74

27.31

27.52

21.47

21.18

21.30

AgenticGEO(ours)\*

34.96

34.25

34.10

26.79

26.57

26.58

33.63

33.82

33.50

26.38

26.63

26.88

Gains (%\\%)

74.89

69.98

70.07

46.39

46.88

47.58

72.90

72.20

70.31

33.91

36.92

36.59

### 5.3. Transferability to Unseen Domains (RQ2).

To evaluate AgenticGEO’s cross-domain transferability, we test AgenticGEO on MS MARCO and E-Commerce without domain-specific fine-tuning. As shown in Table [3](#S5.T3 "Table 3 ‣ 5.2. Overall Performance and Robustness (RQ1). ‣ 5. Experiments ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization"), our method exhibits strong robustness against domain shifts, whereas baselines suffer from significant performance degradation. On MS MARCO, AgenticGEO outperforms the strongest baseline, AutoGEO, by over 11% on both Qwen2.5-32B-Instruct and Llama3.3-70B-Instruct. And the advantage is even more dominant on the E-Commerce dataset.

The transferability gains across two unseen domains support the claim that AgenticGEO avoids overfitting to specific content. The design of an evolving strategy archive and critic-guided planning yields a transferable optimization policy that remains effective under domain shift, showing strong domain generalization.

### 5.4. Ablation Analysis (RQ3)

##### Impact of Core Components.

Figure [4](#S5.F4 "Figure 4 ‣ Impact of Core Components. ‣ 5.4. Ablation Analysis (RQ3) ‣ 5. Experiments ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") shows that removing any of the components degrades performance on all datasets. The largest drop comes from removing the evolved strategy archive (b), confirming that long-term strategy accumulation is the primary driver of gains. Using an offline-only critic (a) is also clearly weaker, highlighting the importance of online co-evolution and continual critic recalibration. Replacing critic-guided planning with random planning (c) and maintaining the archive by performance only (d) cause degrades, suggesting diversity-aware archive improves generability.

![Refer to caption](2603.20213v1/x4.png)

Figure 4. Ablation study of AgenticGEO on three datasets. We compare AgenticGEO with four variants: (a) an offline-only critic trained without online co-evolution, (b) removing the evolved strategy archive, (c) replacing the critic with random rewrite planning and the evolver directly generates the strategy, (d) maintaining the archive by performance only without diversity.

##### Impact of Hyper-parameters.

Figure [5](#S5.F5 "Figure 5 ‣ Impact of Hyper-parameters. ‣ 5.4. Ablation Analysis (RQ3) ‣ 5. Experiments ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") evaluates the hyperparameters of AgenticGEO on GEO-Bench. Multi-turn rewriting works best at 33 turns (overall 25.4825.48), while adding more turns brings only small gains, indicating that a short planning is enough in practice. Archive size works best with a medium archive (2525–3535 strategies), peaking at 3535, whereas very small or very large archives perform worse, reflecting a trade-off between exploration and exploitation.

![Refer to caption](2603.20213v1/x5.png)

Figure 5. Hyper-parameter sensitivity analysis on GEO-Bench. We report overall impression score when varying the multi-turn rewriting steps (left) and the archive size (right).

Table 4. Offline critic ranking quality.

Benchmark

NDCG@1

NDCG@3

NDCG@5

GEO-Bench

84.01

93.89

94.98

Ms-Marco

77.73

81.39

82.82

E-Commerce

68.47

73.77

78.46

![\[Uncaptioned image\]](2603.20213v1/x6.png)

Figure 6. Effect of the amount of GE feedback on overall performance when evolving.

![Refer to caption](2603.20213v1/x7.png)

Figure 7. Semantic consistency and optimization effectiveness. Semantic Similarity is measured by BERTScore-F1 (Zhang et al., [2019](#bib.bib62)) with roberta-large (Liu et al., [2019](#bib.bib28)), computed between the original content and the rewritten version.

##### Impact of Offline Critic Alignment.

We evaluate the efficacy of offline pre-training as a warm-start for online co-evolutionary learning. The critic is prompted to predict how the downstream engine would rank the seed strategies, comparing to the ground-truth with NDCG@K (Järvelin and Kekäläinen, [2002](#bib.bib21)) metrics. Table [4](#S5.T4 "Table 4 ‣ Impact of Hyper-parameters. ‣ 5.4. Ablation Analysis (RQ3) ‣ 5. Experiments ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") shows that the offline-pretrained critic achieves consistently high NDCG across all datasets, including two unseen domains. On GEO-Bench, the critic closely matches the engine-derived preference ordering, with an NDCG@5 of approximately 95%95\\%. While performance degrades on unseen domains, the critic still preserves strong top-rank fidelity, suggesting that it captures transferable signals rather than overfitting to the training distribution. These findings validate that the offline aligned critic model can serve as a reliable surrogate evaluator.

##### The role of critic as the surrogate of GE at online evolution

As Figure [6](#S5.F6 "Figure 6 ‣ Impact of Hyper-parameters. ‣ 5.4. Ablation Analysis (RQ3) ‣ 5. Experiments ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") shows, by using the critic as a low-cost surrogate of the GE environment, we can substantially reduce expensive GE interactions without sacrificing much performance. With only 700700 GE feedback, our method reaches an overall score of 25.1225.12, preserving 98.1%98.1\\% of the best performance (25.6025.60) while using only 41.2%41.2\\% of the GE supervision, demonstrating sample-efficient online evolution under a limited feedback budget.

### 5.5. Semantic Consistency Evaluation (RQ4)

Figure [7](#S5.F7 "Figure 7 ‣ Impact of Hyper-parameters. ‣ 5.4. Ablation Analysis (RQ3) ‣ 5. Experiments ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") compares the trade-off between semantic similarity and gains in overall scores. Most heuristic baselines preserve semantics well but yield limited improvements, suggesting that small edits alone are often insufficient to meaningfully increase a document’s influence on visibility and attribution in the synthesized answers. AutoGEO achieves stronger overall performance, yet its semantic similarity is noticeably lower, indicating that its gains may come at the cost of larger content drift and information loss. In contrast, AgenticGEO attains the best overall score while maintaining relatively high semantic similarity, demonstrating that it can strengthen a document’s impact on the generated answers without information loss. This indicates that AgenticGEO does not rely on aggressive rewriting. It leverages content-aware strategy selection and moderate, targeted edits that enhance salience and evidence presentation while largely preserving the original meaning.

## 6\. Conclusion

We study Generative Engine Optimization (GEO) for black-box engines, shifting the objective from rank to visibility in synthesized outputs. We show that static heuristics lack adaptability under content heterogeneity and changing GE behaviors. To address high interaction costs, we introduce a lightweight, calibrated critic as a reliable proxy. Built on this, AgenticGEO enables content-adaptive, self-evolving optimization by co-evolving a diverse strategy archive with the critic. Across representative settings, AgenticGEO delivers consistent improvements and strong cross-domain transfer. Our study points to a sustainable direction for web ecosystem governance that rewards quality and diversity, fostering a mutually beneficial development for creators and engines.

## References

-   (1)
-   Aggarwal et al. (2024) Pranjal Aggarwal, Vishvak Murahari, Tanmay Rajpurohit, Ashwin Kalyan, Karthik Narasimhan, and Ameet Deshpande. 2024. Geo: Generative engine optimization. In _Proceedings of the 30th ACM SIGKDD Conference on Knowledge Discovery and Data Mining_. 5–16.
-   Almukhtar et al. (2021) Firas Almukhtar, Nawzad Mahmoodd, and Shahab Kareem. 2021. Search engine optimization: a review. _Applied computer science_ 17, 1 (2021), 70–80.
-   Bing Search Blog (2024) Bing Search Blog. 2024. _Introducing Bing generative search_. [https://blogs.bing.com/search/July-2024/generativesearch](https://blogs.bing.com/search/July-2024/generativesearch)
-   Brantner et al. (2025) Cornelia Brantner, Michael Karlsson, and Joanne Kuai. 2025. Sourcing behavior and the role of news media in AI-powered search engines in the digital media ecosystem: Comparing political news retrieval across five languages. _Telecommunications Policy_ (2025), 102952.
-   Brin and Page (1998) Sergey Brin and Lawrence Page. 1998. The Anatomy of a Large-Scale Hypertextual Web Search Engine. _Computer Networks and ISDN Systems_ 30, 1–7 (1998), 107–117. [doi:10.1016/S0169-7552(98)00110-X](https://doi.org/10.1016/S0169-7552\(98\)00110-X)
-   Broder (1997) Andrei Z Broder. 1997. On the resemblance and containment of documents. In _Proceedings. Compression and Complexity of SEQUENCES 1997 (Cat. No. 97TB100171)_. IEEE, 21–29.
-   Cai (2025) Kenrick Cai. 2025. _Google tests an AI-only version of its search engine_. Reuters. [https://www.reuters.com/technology/artificial-intelligence/google-tests-an-ai-only-version-its-search-engine-2025-03-05/](https://www.reuters.com/technology/artificial-intelligence/google-tests-an-ai-only-version-its-search-engine-2025-03-05/)
-   Chen et al. (2025a) Mahe Chen, Xiaoxuan Wang, Kaiwen Chen, and Nick Koudas. 2025a. Generative engine optimization: How to dominate ai search. _arXiv preprint arXiv:2509.08919_ (2025).
-   Chen et al. (2025b) Xiaolu Chen, Haojie Wu, Jie Bao, Zhen Chen, Yong Liao, and Hu Huang. 2025b. Role-Augmented Intent-Driven Generative Search Engine Optimization. _arXiv preprint arXiv:2508.11158_ (2025).
-   Deb et al. (2002) Kalyanmoy Deb, Amrit Pratap, Sameer Agarwal, and TAMT Meyarivan. 2002. A fast and elitist multiobjective genetic algorithm: NSGA-II. _IEEE transactions on evolutionary computation_ 6, 2 (2002), 182–197.
-   Fang et al. (2025) Jinyuan Fang, Yanwen Peng, Xi Zhang, Yingxu Wang, Xinhao Yi, Guibin Zhang, Yi Xu, Bin Wu, Siwei Liu, Zihao Li, et al. 2025. A comprehensive survey of self-evolving ai agents: A new paradigm bridging foundation models and lifelong agentic systems. _arXiv preprint arXiv:2508.07407_ (2025).
-   Fernando et al. (2023) Chrisantha Fernando, Dylan Banarse, Henryk Michalewski, Simon Osindero, and Tim Rocktäschel. 2023. Promptbreeder: Self-referential self-improvement via prompt evolution. _arXiv preprint arXiv:2309.16797_ (2023).
-   Gao et al. (2023) Yunfan Gao, Yun Xiong, Xinyu Gao, Kangxiang Jia, Jinliu Pan, Yuxi Bi, Yixin Dai, Jiawei Sun, Haofen Wang, and Haofen Wang. 2023. Retrieval-augmented generation for large language models: A survey. _arXiv preprint arXiv:2312.10997_ 2, 1 (2023).
-   Grattafiori et al. (2024) Aaron Grattafiori, Abhimanyu Dubey, Abhinav Jauhri, Abhinav Pandey, Abhishek Kadian, Ahmad Al-Dahle, Aiesha Letman, Akhil Mathur, and et al. 2024. The Llama 3 Herd of Models. arXiv:2407.21783 \[cs.AI\] [https://arxiv.org/abs/2407.21783](https://arxiv.org/abs/2407.21783)
-   Guo et al. (2023) Qingyan Guo, Rui Wang, Junliang Guo, Bei Li, Kaitao Song, Xu Tan, Guoqing Liu, Jiang Bian, and Yujiu Yang. 2023. Connecting large language models with evolutionary algorithms yields powerful prompt optimizers. _arXiv preprint arXiv:2309.08532_ (2023).
-   Hu et al. (2022) Edward J Hu, Yelong Shen, Phillip Wallis, Zeyuan Allen-Zhu, Yuanzhi Li, Shean Wang, Lu Wang, Weizhu Chen, et al. 2022. Lora: Low-rank adaptation of large language models. _ICLR_ 1, 2 (2022), 3.
-   Hu et al. (2025) Mengkang Hu, Pu Zhao, Can Xu, Qingfeng Sun, Jian-Guang Lou, Qingwei Lin, Ping Luo, and Saravan Rajmohan. 2025. Agentgen: Enhancing planning abilities for large language model based agent via environment and task generation. In _Proceedings of the 31st ACM SIGKDD Conference on Knowledge Discovery and Data Mining V. 1_. 496–507.
-   Huber (1992) Peter J Huber. 1992. Robust estimation of a location parameter. In _Breakthroughs in statistics: Methodology and distribution_. Springer, 492–518.
-   Izacard and Grave (2021) Gautier Izacard and Edouard Grave. 2021. Leveraging passage retrieval with generative models for open domain question answering. In _Proceedings of the 16th conference of the european chapter of the association for computational linguistics: main volume_. 874–880.
-   Järvelin and Kekäläinen (2002) Kalervo Järvelin and Jaana Kekäläinen. 2002. Cumulated gain-based evaluation of IR techniques. _ACM Transactions on Information Systems (TOIS)_ 20, 4 (2002), 422–446.
-   Justesen et al. (2019) Niels Justesen, Sebastian Risi, and Jean-Baptiste Mouret. 2019. Map-elites for noisy domains by adaptive sampling. In _Proceedings of the genetic and evolutionary computation conference companion_. 121–122.
-   Kumar and Lakkaraju (2024) Aounon Kumar and Himabindu Lakkaraju. 2024. Manipulating large language models to increase product visibility. _arXiv preprint arXiv:2404.07981_ (2024).
-   Lehman and Stanley (2011) Joel Lehman and Kenneth O Stanley. 2011. Evolving a diversity of virtual creatures through novelty search and local competition. In _Proceedings of the 13th annual conference on Genetic and evolutionary computation_. 211–218.
-   Lewandowski et al. (2021) Dirk Lewandowski, Sebastian Sünkler, and Nurce Yagci. 2021. The influence of search engine optimization on Google’s results: A multi-dimensional approach for detecting SEO. In _Proceedings of the 13th ACM Web Science Conference 2021 (WebSci ’21)_. ACM, 9 pages. [doi:10.1145/3447535.3462479](https://doi.org/10.1145/3447535.3462479)
-   Lewis et al. (2020) Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni, Vladimir Karpukhin, Naman Goyal, Heinrich Küttler, Mike Lewis, Wen-tau Yih, Tim Rocktäschel, et al. 2020. Retrieval-augmented generation for knowledge-intensive nlp tasks. _Advances in neural information processing systems_ 33 (2020), 9459–9474.
-   Li et al. (2025) Junjun Li, Zeyuan Ma, Ting Huang, and Yue-Jiao Gong. 2025. Learn to Refine: Synergistic Multi-Agent Path Optimization for Lifelong Conflict-Free Navigation of Autonomous Vehicles. In _Proceedings of the 31st ACM SIGKDD Conference on Knowledge Discovery and Data Mining V. 2_. 1400–1411.
-   Liu et al. (2019) Yinhan Liu, Myle Ott, Naman Goyal, Jingfei Du, Mandar Joshi, Danqi Chen, Omer Levy, Mike Lewis, Luke Zettlemoyer, and Veselin Stoyanov. 2019. Roberta: A robustly optimized bert pretraining approach. _arXiv preprint arXiv:1907.11692_ (2019).
-   Liu et al. (2025) Yuxuan Liu, Hongda Sun, Wei Liu, Jian Luan, Bo Du, and Rui Yan. 2025. MobileSteward: Integrating Multiple App-Oriented Agents with Self-Evolution to Automate Cross-App Instructions. In _Proceedings of the 31st ACM SIGKDD Conference on Knowledge Discovery and Data Mining V. 1_. 883–893.
-   Madaan et al. (2023) Aman Madaan, Niket Tandon, Prakhar Gupta, Skyler Hallinan, Luyu Gao, Sarah Wiegreffe, Uri Alon, Nouha Dziri, Shrimai Prabhumoye, Yiming Yang, et al. 2023. Self-refine: Iterative refinement with self-feedback. _Advances in Neural Information Processing Systems_ 36 (2023), 46534–46594.
-   Malaga (2010) Ross A Malaga. 2010. Search engine optimization—black and white hat approaches. In _Advances in computers_. Vol. 78. Elsevier, 1–39.
-   Manning et al. (2008) Christopher D. Manning, Prabhakar Raghavan, and Hinrich Schütze. 2008. _Introduction to Information Retrieval_. Cambridge University Press.
-   Menick et al. (2022) Jacob Menick, Maja Trebacz, Vladimir Mikulik, John Aslanides, Francis Song, Martin Chadwick, Mia Glaese, Susannah Young, Lucy Campbell-Gillingham, Geoffrey Irving, et al. 2022. Teaching language models to support answers with verified quotes, 2022. _URL https://arxiv. org/abs/2203.11147_ (2022).
-   Mouret and Clune (2015) Jean-Baptiste Mouret and Jeff Clune. 2015. Illuminating search spaces by mapping elites. _arXiv preprint arXiv:1504.04909_ (2015).
-   Nakano et al. (2021) Reiichiro Nakano, Jacob Hilton, Suchir Balaji, Jeff Wu, Long Ouyang, Christina Kim, Christopher Hesse, Shantanu Jain, Vineet Kosaraju, William Saunders, et al. 2021. Webgpt: Browser-assisted question-answering with human feedback. _arXiv preprint arXiv:2112.09332_ (2021).
-   Nakano et al. (2022) Reiichiro Nakano, Jacob Hilton, Suchir Balaji, Jeff Wu, Long Ouyang, Christina Kim, Christopher Hesse, Shantanu Jain, Vineet Kosaraju, William Saunders, et al. 2022. Webgpt: Browser-assisted question-answering with human feedback, 2022. _URL https://arxiv. org/abs/2112.09332_ (2022).
-   Nestaas et al. (2024) Fredrik Nestaas, Edoardo Debenedetti, and Florian Tramèr. 2024. Adversarial search engine optimization for large language models. _arXiv preprint arXiv:2406.18382_ (2024).
-   Nguyen et al. (2016) Tri Nguyen, Mir Rosenberg, Xia Song, Jianfeng Gao, Saurabh Tiwary, Rangan Majumder, and Li Deng. 2016. Ms marco: A human-generated machine reading comprehension dataset. (2016).
-   Ouyang et al. (2022) Long Ouyang, Jeff Wu, Xu Jiang, Diogo Almeida, Carroll L. Wainwright, Pamela Mishkin, Chong Zhang, Sandhini Agarwal, Katarina Slama, Alex Ray, John Schulman, Jacob Hilton, Fraser Kelton, Luke Miller, Maddie Simens, Amanda Askell, Peter Welinder, Paul Christiano, Jan Leike, and Ryan Lowe. 2022. Training language models to follow instructions with human feedback. _arXiv preprint arXiv:2203.02155_ (2022). arXiv:2203.02155 \[cs.CL\]
-   Page et al. (1999) Lawrence Page, Sergey Brin, Rajeev Motwani, and Terry Winograd. 1999. _The PageRank citation ranking: Bringing order to the web._ Technical Report. Stanford infolab.
-   Perplexity Support (\[n. d.\]) Perplexity Support. \[n. d.\]. _How does Perplexity work?_ Perplexity Help Center. [https://www.perplexity.ai/help-center/en/articles/10352895-how-does-perplexity-work](https://www.perplexity.ai/help-center/en/articles/10352895-how-does-perplexity-work)
-   Pugh et al. (2016) Justin K Pugh, Lisa B Soros, and Kenneth O Stanley. 2016. Quality diversity: A new frontier for evolutionary computation. _Frontiers in Robotics and AI_ 3 (2016), 40.
-   Reddy et al. (2022) Chandan K Reddy, Lluís Màrquez, Fran Valero, Nikhil Rao, Hugo Zaragoza, Sambaran Bandyopadhyay, Arnab Biswas, Anlu Xing, and Karthik Subbian. 2022. Shopping queries dataset: A large-scale ESCI benchmark for improving product search. _arXiv preprint arXiv:2206.06588_ (2022).
-   Saeed et al. (2024) Zafar Saeed, Fozia Aslam, Adnan Ghafoor, Muhammad Umair, and Imran Razzak. 2024. Exploring the impact of SEO-based ranking factors for voice queries through machine learning. _Artificial Intelligence Review_ 57, 6 (2024), 144.
-   Sclar et al. (2024) Melanie Sclar, Yejin Choi, Yulia Tsvetkov, and Alane Suhr. 2024. Quantifying Language Models’ Sensitivity to Spurious Features in Prompt Design or: How I Learned to Start Worrying about Prompt Formatting. In _International Conference on Learning Representations (ICLR)_.
-   Shahzad et al. (2020) Asim Shahzad, Deden Witarsyah Jacob, Nazri Mohd Nawi, Hairulnizam Mahdin, and Marheni Eka Saputri. 2020. The new trend for search engine optimization, tools and techniques. _Indonesian Journal of Electrical Engineering and Computer Science_ 18, 3 (2020), 1568–1583.
-   Shao et al. (2024) Zhihong Shao, Peiyi Wang, Qihao Zhu, Runxin Xu, Junxiao Song, Xiao Bi, Haowei Zhang, Mingchuan Zhang, Y.K. Li, Y. Wu, and Daya Guo. 2024. DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models. _arXiv preprint arXiv:2402.03300_ (2024). arXiv:2402.03300 \[cs.CL\]
-   Sharma et al. (2019) Dushyant Sharma, Rishabh Shukla, Anil Kumar Giri, and Sumit Kumar. 2019. A brief review on search engine optimization. In _2019 9th international conference on cloud computing, data science & engineering (confluence)_. IEEE, 687–692.
-   Shinn et al. (2023) Noah Shinn, Federico Cassano, Beck Labash, Ashwin Gopinath, Karthik Narasimhan, and Shunyu Yao. 2023. Reflexion: Language agents with verbal reinforcement learning, 2023. _URL https://arxiv. org/abs/2303.11366_ 1 (2023).
-   Stein (2025) Robby Stein. 2025. _Expanding AI Overviews and introducing AI Mode_. [https://blog.google/products-and-platforms/products/search/ai-mode-search/](https://blog.google/products-and-platforms/products/search/ai-mode-search/)
-   Sun et al. (2023) Haotian Sun, Yuchen Zhuang, Lingkai Kong, Bo Dai, and Chao Zhang. 2023. Adaplanner: Adaptive planning from feedback with language models. _Advances in neural information processing systems_ 36 (2023), 58202–58245.
-   Team (2025) Qwen Team. 2025. Qwen2.5 Technical Report. arXiv:2412.15115 \[cs.CL\] [https://arxiv.org/abs/2412.15115](https://arxiv.org/abs/2412.15115)
-   Wang et al. (2023) Guanzhi Wang, Yuqi Xie, Yunfan Jiang, Ajay Mandlekar, Chaowei Xiao, Yuke Zhu, Linxi Fan, and Anima Anandkumar. 2023. Voyager: An open-ended embodied agent with large language models. _arXiv preprint arXiv:2305.16291_ (2023).
-   Wang et al. (2025) Yingxu Wang, Siwei Liu, Jinyuan Fang, and Zaiqiao Meng. 2025. Evoagentx: An automated framework for evolving agentic workflows. In _Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing: System Demonstrations_. 643–655.
-   Wu et al. (2025) Yujiang Wu, Shanshan Zhong, Yubin Kim, and Chenyan Xiong. 2025. What Generative Search Engines Like and How to Optimize Web Content Cooperatively. _arXiv preprint arXiv:2510.11438_ (2025).
-   Yang et al. (2023) Chengrun Yang, Xuezhi Wang, Yifeng Lu, Hanxiao Liu, Quoc V Le, Denny Zhou, and Xinyun Chen. 2023. Large language models as optimizers. In _The Twelfth International Conference on Learning Representations_.
-   Yao et al. (2022) Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik R Narasimhan, and Yuan Cao. 2022. React: Synergizing reasoning and acting in language models. In _The eleventh international conference on learning representations_.
-   Yuksel et al. (2025) Kamer Ali Yuksel, Thiago Castro Ferreira, Mohamed Al-Badrashiny, and Hassan Sawaf. 2025. A multi-AI agent system for autonomous optimization of agentic AI solutions via iterative refinement and LLM-driven feedback loops. In _Proceedings of the 1st Workshop for Research on Agent Language Models (REALM 2025)_. 52–62.
-   Zhai et al. (2025) Yunpeng Zhai, Shuchang Tao, Cheng Chen, Anni Zou, Ziqian Chen, Qingxu Fu, Shinji Mai, Li Yu, Jiaji Deng, Zouying Cao, et al. 2025. Agentevolver: Towards efficient self-evolving agent system. _arXiv preprint arXiv:2511.10395_ (2025).
-   Zhang et al. (2024) Jiayi Zhang, Jinyu Xiang, Zhaoyang Yu, Fengwei Teng, Xionghui Chen, Jiaqi Chen, Mingchen Zhuge, Xin Cheng, Sirui Hong, Jinlin Wang, et al. 2024. Aflow: Automating agentic workflow generation. _arXiv preprint arXiv:2410.10762_ (2024).
-   Zhang et al. (2025a) Qizheng Zhang, Changran Hu, Shubhangi Upasani, Boyuan Ma, Fenglu Hong, Vamsidhar Kamanuru, Jay Rainton, Chen Wu, Mengmeng Ji, Hanchen Li, et al. 2025a. Agentic context engineering: Evolving contexts for self-improving language models. _arXiv preprint arXiv:2510.04618_ (2025).
-   Zhang et al. (2019) Tianyi Zhang, Varsha Kishore, Felix Wu, Kilian Q Weinberger, and Yoav Artzi. 2019. Bertscore: Evaluating text generation with bert. _arXiv preprint arXiv:1904.09675_ (2019).
-   Zhang et al. (2025b) Yao Zhang, Chenyang Lin, Shijie Tang, Haokun Chen, Shijie Zhou, Yunpu Ma, and Volker Tresp. 2025b. SwarmAgentic: Towards Fully Automated Agentic System Generation via Swarm Intelligence. _arXiv preprint arXiv:2506.15672_ (2025).
-   Zhou et al. (2022) Yongchao Zhou, Andrei Ioan Muresanu, Ziwen Han, Keiran Paster, Silviu Pitis, Harris Chan, and Jimmy Ba. 2022. Large language models are human-level prompt engineers. In _The eleventh international conference on learning representations_.
-   Ziakis et al. (2019) Christos Ziakis, Maro Vlachopoulou, Theodosios Kyrkoudis, and Makrina Karagkiozidou. 2019. Important factors for improving Google search rank. Future Internet, 11 (2), 32.

## Appendix A Supplementary Information

### A.1. Methodological Details

#### A.1.1. Explanation of Figure[1](#S1.F1 "Figure 1 ‣ 1. Introduction ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")

For each instance, we run the nine rewriting strategies and obtain their average overall scores {ri}i\=19\\{r\_{i}\\}\_{i=1}^{9}, with the best score r⋆\=maxi⁡rir^{\\star}=\\max\_{i}r\_{i}. We quantify how many strategies remain competitive relative to the best. A strategy is considered near-optimal if it achieves at least 55%55\\% of r⋆r^{\\star} (equivalently, its gap to r⋆r^{\\star} is no more than 45%45\\% of r⋆r^{\\star}). Sensitivity is defined as the complement of this near-optimal fraction:

Sensitivity\=1−19​∑i\=19𝕀​\[ri≥0.55​r⋆\]∈\[0,1\].\\text{Sensitivity}=1-\\frac{1}{9}\\sum\_{i=1}^{9}\\mathbb{I}\\!\\left\[r\_{i}\\geq 0.55\\,r^{\\star}\\right\]\\in\[0,1\].

Higher values indicate that only a few strategies are competitive (high sensitivity), whereas lower values suggest many strategies perform similarly well (low sensitivity).

With normalized sensitivity on the x-axis and maximum gain on the y-axis, we split instances into four regions. _(i) Robustly Optimizable_: many strategies achieve similarly high gains. _(ii) Strategy-Dependent_: high gains exist, but only a few strategies work well. _(iii) Optimization-Resistant_: strategies behave similarly and gains remain small. _(iv) Low-Yield & Volatile_: outcomes vary widely, yet the best gain is still small.

The figure gives us two insights. First, GEO is instance-dependent, so a fixed strategy pool is unreliable. Second, _Strategy-Dependent_ region motivates content-conditioned strategy selection.

#### A.1.2. Cited answer output

The engine output is a cited answer 𝒜\={(yi,𝒞i)}i\=0L−1\\mathcal{A}=\\{(y\_{i},\\mathcal{C}\_{i})\\}\_{i=0}^{L-1}, where LL is the number of generated sentences, yiy\_{i} is the ii\-th sentence, and 𝒞i⊆{1,…,n}\\mathcal{C}\_{i}\\subseteq\\{1,\\dots,n\\} denotes the indices of candidate documents cited in yiy\_{i}. Let j⋆j^{\\star} denote the index of the optimized content d′d^{\\prime} within the candidate set. To standardize ℰ\\mathcal{E}’s cited-answer generation, we use the following prompt template.

Engine Answer Synthesis Prompt Template Write an accurate and concise answer for the given user question. using only the provided summarized web search results. The answer should be correct, high-quality, and written by an expert using an unbiased and journalistic tone. The user’s language of choice, such as English, Français, Español, or Deutsch should be used. The answer should be informative, interesting, and engaging. The answer’s logic and reasoning should be rigorous and defensible. Every sentence in the answer should be immediately followed by an in-line citation to the search result(s). The cited search result(s) should fully support all the information in the sentence. Search results need to be cited using \[index\]. When citing several search results, use \[1\]\[2\]\[3\] format rather than \[1, 2, 3\]. You can use multiple search results to respond comprehensively while avoiding irrelevant search results.

#### A.1.3. Impression metrics

Following GEO-Bench (Aggarwal et al., [2024](#bib.bib2)), we quantify the visibility of each candidate document j∈{1,…,n}j\\in\\{1,\\dots,n\\} within the generated response 𝒜\={y0,…,yL−1}\\mathcal{A}=\\{y\_{0},\\dots,y\_{L-1}\\} by aggregating its attributed contributions. Here, yiy\_{i} denotes the ii\-th sentence in 𝒜\\mathcal{A}, and 𝒞i\\mathcal{C}\_{i} denotes the set of citation indices associated with yiy\_{i}. When a sentence cites multiple candidates, its contribution is uniformly distributed by a factor of 1/|𝒞i|1/|\\mathcal{C}\_{i}|.

Let wc​(yi)\\mathrm{wc}(y\_{i}) be the word count of sentence yiy\_{i}. To reflect user attention decay, we define a position weight w​(i)w(i) for the ii\-th sentence:

(15)

w​(i)\={exp⁡(−iL−1),L\>1,1,L\=1.w(i)=\\begin{cases}\\exp\\!\\left(-\\frac{i}{L-1}\\right),&L>1,\\\\ 1,&L=1.\\end{cases}

We compute three impression scores: word (attributed word count), pos (citation order with position weights), and overall (a combination of word count and position decay):

(16)

Scorejword​(q,s)\\displaystyle\\mathrm{Score}^{\\textsc{word}}\_{j}(q,s)

\=∑i\=0L−1𝕀​\[j∈𝒞i\]⋅wc​(yi)|𝒞i|,\\displaystyle=\\sum\_{i=0}^{L-1}\\mathbb{I}\[j\\in\\mathcal{C}\_{i}\]\\cdot\\frac{\\mathrm{wc}(y\_{i})}{|\\mathcal{C}\_{i}|},

(17)

Scorejpos​(q,s)\\displaystyle\\mathrm{Score}^{\\textsc{pos}}\_{j}(q,s)

\=∑i\=0L−1𝕀​\[j∈𝒞i\]⋅w​(i)|𝒞i|,\\displaystyle=\\sum\_{i=0}^{L-1}\\mathbb{I}\[j\\in\\mathcal{C}\_{i}\]\\cdot\\frac{w(i)}{|\\mathcal{C}\_{i}|},

(18)

Scorejoverall​(q,s)\\displaystyle\\mathrm{Score}^{\\textsc{overall}}\_{j}(q,s)

\=∑i\=0L−1𝕀​\[j∈𝒞i\]⋅wc​(yi)⋅w​(i)|𝒞i|.\\displaystyle=\\sum\_{i=0}^{L-1}\\mathbb{I}\[j\\in\\mathcal{C}\_{i}\]\\cdot\\frac{\\mathrm{wc}(y\_{i})\\cdot w(i)}{|\\mathcal{C}\_{i}|}.

The goal of GEO is to maximize the impression of the optimized content d~\\tilde{d} in the generative engine output 𝒜\\mathcal{A}, as quantified by the above metrics.

#### A.1.4. Seed Strategies

We initialize the critic’s offline preference alignment with 9 seed rewriting strategies. Each seed prompt is a template applied to the source summary (placeholder {summary}) to produce candidate rewrites, which are then used to construct offline preference data for warm-starting the critic.

Keyword Stuffing Task: Improve the source by inserting up to 10 NEW, relevant SEO keywords that are NOT already present in the text. Constraints: – Do not change, add, or remove any core information. – Keep the original structure (paragraphing, bullet points, line breaks). – Insert keywords naturally inline (no keyword list at the end). Source: summary Output: The updated source text only.

Unique Words Task: Revise the source by using more unique and precise vocabulary. Constraints: – Preserve the original meaning and all core information. – Do not add new claims or remove any content. – Keep the length and structure roughly the same. Source: summary Output: The revised source text only.

Easy-To-Understand Task: Rewrite the source in simple, easy-to-understand language. Constraints: – Do not omit, add, or alter any core information. – Keep the original structure and roughly the same length. – Only rephrase sentences for clarity and readability. Source: summary Output: The simplified source text only.

Authoritative Task: Make the source sound confident, authoritative, and expert. Constraints: – Do not add new facts or remove any information. – Keep the original structure (formatting, bullets, spacing). – Strengthen tone via wording choices, not by exaggerating or making unverifiable claims. Source: summary Output: The revised source text only.

Technical Words Task: Rewrite the source in a more technical style using domain-appropriate terminology. Constraints: – Preserve all core information; do not introduce new claims. – Keep the structure and length roughly unchanged. – Rephrase sentences to sound more technical and precise. Source: summary Output: The revised source text only.

Fluency Optimization Task: Rewrite the source to improve fluency and coherence. Constraints: – Do not alter the core content. – Improve sentence transitions and readability. – Keep the structure and length roughly the same. Source: summary Output: The rewritten source text only.

Cite Sources Task: Strengthen credibility by adding a small number of natural-language citations to credible sources (e.g., industry reports, standards, official docs). Constraints: – Citations must be plausible and verifiable; do not fabricate sources. – Do not change the core information or add new claims. – Keep structure and length roughly the same (about 5–6 citations total). Source: summary Output: The revised source text only.

Quotation Addition Task: Increase perceived authority by adding a few short, relevant quotations from reputable entities (e.g., well-known organizations or experts). Constraints: – Quotes must be accurate and attributable; do not invent quotes. – Do not change core content; keep structure and length similar. – Integrate quotes inline without adding long new paragraphs. Source: summary Output: The revised source text only.

Statistics Addition Task: Add a few concise, relevant statistics or numerical facts to improve concreteness. Constraints: – Statistics must be verifiable; do not invent numbers. – Do not modify core content beyond inserting stats inline. – Keep the original structure and stop at the end of the original source. Source: summary Output: The revised source text only.

#### A.1.5. Genotype Details

We formalize the evolving strategy as a structured genotype g\=⟨gI,gC,gR,gF,gT⟩g=\\langle g^{I},g^{C},g^{R},g^{F},g^{T}\\rangle. To interface efficiently with the Critic and the Generative Engine, we implement two deterministic rendering functions RcritR\_{\\text{crit}} and RengR\_{\\text{eng}} :

1\. Compact Summary for Critic (RcritR\_{\\text{crit}}). To minimize token consumption while retaining discriminative features, Rcrit​(g)R\_{\\text{crit}}(g) maps the genotype to a concatenated string of active categorical values. Formally, let 𝒦active⊂g\\mathcal{K}\_{\\text{active}}\\subset g be the set of non-empty discrete fields (e.g., tone labels, format types). The rendering is defined as:

(19)

Rcrit​(g)\=⨁k∈𝒦active(Name​(k)​‖”:”‖​Val​(k)),R\_{\\text{crit}}(g)=\\bigoplus\_{k\\in\\mathcal{K}\_{\\text{active}}}\\left(\\text{Name}(k)||\\text{":"}||\\text{Val}(k)\\right),

where ⊕\\oplus denotes string concatenation with delimiters. For example, a strategy might be rendered as “Tone:Assertive|Format:List| Constraint:Anti-Hallucination”.

2\. Full Prompt for Engine (RengR\_{\\text{eng}}). Reng​(g)R\_{\\text{eng}}(g) acts as a template-filling function that constructs the executable meta-prompt. It wraps the raw text of each gene component into specific sections:

(20)

Reng​(g)\=𝒯sys⊕gI⊕𝒯cons​(gC)⊕𝒯reason​(gR)⊕𝒯fmt​(gF)⊕𝒯tone​(gT),R\_{\\text{eng}}(g)=\\mathcal{T}\_{\\text{sys}}\\oplus g^{I}\\oplus\\mathcal{T}\_{\\text{cons}}(g^{C})\\oplus\\mathcal{T}\_{\\text{reason}}(g^{R})\\oplus\\mathcal{T}\_{\\text{fmt}}(g^{F})\\oplus\\mathcal{T}\_{\\text{tone}}(g^{T}),

where 𝒯\\mathcal{T} represents fixed instructional templates (e.g., “Adhere to the following constraints: …”). This full prompt is then combined with the query qq and content dd to form the final input for the rewriting model.

#### A.1.6. MAP-Elites Descriptors and Archive Gates

The strategy space is discretized into behavioral cells via a descriptor function ψ:𝒢→ℤD\\psi:\\mathcal{G}\\to\\mathbb{Z}^{D}. Based on our design, ψ​(g)\\psi(g) maps a genotype to a tuple of 12 discrete dimensions :

-   •

    Core Types: strategy\_type, output\_schema.

-   •

    Switches: has\_self\_check, has\_reasoning, has\_conflict\_res, use\_code\_block, has\_prelude, has\_post\_check.

-   •

    Buckets: tone\_bucket, constraint\_strength, length\_policy, reasoning\_steps\_bucket.


A candidate strategy ss (with genotype gg) is mapped to a cell index c\=ψ​(g)c=\\psi(g). It is admitted only if it passes two gates:

1\. Novelty Gate (De-duplication). We de-duplicate candidates using character-level nn\-gram Jaccard similarity computed on the rendered strategy summaries. The similarity between a candidate ss and an existing elite ee is:

(21)

Sim⁡(s,e)\=|n\-grams​(s)∩n\-grams​(e)||n\-grams​(s)∪n\-grams​(e)|.\\operatorname{Sim}(s,e)=\\frac{|\\text{$n$-grams}(s)\\cap\\text{$n$-grams}(e)|}{|\\text{$n$-grams}(s)\\cup\\text{$n$-grams}(e)|}.

The candidate is rejected if it is too similar to any strategy already stored in the target cell:

maxe⁡Sim⁡(s,e)\>0.9,\\max\_{e}\\operatorname{Sim}(s,e)>0.9,

which prevents near-duplicates.

2\. Value Gate (Performance). If the target cell is not full (<Kc<K\_{c} strategies), ss is admitted. Otherwise, it must beat the current worst strategy in that cell.

#### A.1.7. PND Score Formulation and Pruning

We maintain the archive using a PND score that balances effectiveness and exploration:

(22)

SPND​(s)\=r​(s)+λpnd​(Nov⁡(s)+Div⁡(s)),S\_{\\mathrm{PND}}(s)=r(s)+\\lambda\_{\\mathrm{pnd}}\\big(\\operatorname{Nov}(s)+\\operatorname{Div}(s)\\big),

where r​(s)r(s) is the impression score gain evaluated by the critic or GE.

Novelty (Nov\\operatorname{Nov}). Nov⁡(s)\\operatorname{Nov}(s) encourages population coverage by rewarding strategies that are structurally dissimilar to those already stored in the current archive ℳ\\mathcal{M} (using similarity metric as Eq. (21)).

Diversity (Div\\operatorname{Div}). Div⁡(s)\\operatorname{Div}(s) promotes diverse evolutionary trajectories by favoring strategies with richer lineage history (e.g., deeper generations), more varied mutation operators, and less degenerate genotypes (more fields actively used).

#### A.1.8. Evolver Action Space and Prompting

The Evolver πψ\\pi\_{\\psi} functions as a meta-optimizer that proposes improvements to existing strategies. It takes as input an instance x\=(q,d)x=(q,d), a primary parent gAg\_{A}, an optional secondary parent gBg\_{B} (for crossover), and an operator catalog Ω\\Omega.

Operator Catalog (Ω\\Omega). To ensure diverse and controllable evolution, Ω\\Omega consists of two categories of symbolic operators.

Mutation Operators apply field-level perturbations targeting specific dimensions, such as mut\_C\_strengthen (adding constraints), mut\_T\_toggle\_tone (switching styles), and mut\_F\_schema\_swap (changing output format).

Crossover Operators synthesize features from two parents, including cx\_swap\_gene (exchanging gene blocks) and cx\_conflict\_sy- nthesis (resolving conflicts between Parent A and B).

Action Proposal. The Evolver outputs MM candidate actions. Each action is a strict JSON object a\={operator\_id,child\_genotype}a=\\{\\texttt{operator\\\_id},\\texttt{child\\\_genotype}\\}, where child\_genotype is the full structure resulting from applying the selected operator.

Evolver Action Proposal Prompt Template System: You are a prompt evolution agent for GEO. You must evolve a parent strategy (or combine two parents) into a better STRUCTURED GENOTYPE JSON (I/C/R/F/T). 1) Choose an operator\_id from the provided catalog. 2) Produce a child\_genotype JSON that results from applying that operator. Important constraints: - The output MUST be valid JSON (one object per line). - The child genotype MUST preserve the I/C/R/F/T structure. - If choosing a Crossover operator (starts with ”cx\_”): You MUST conceptually combine Parent A and Parent B. - If Parent B is NOT provided: Do NOT choose any ”cx\_\*” operator. - Prefer DIVERSITY: Avoid repeating the same operator across candidates. User: ## Query {query} \## Document Summary {content\_summary} \## Parent Genotype A (JSON) {parent\_genotype\_json} \## Parent Genotype B (JSON) \[Optional\] {parent\_b\_genotype\_json} \## Operator Catalog {operator\_catalog} \## Task Generate {num\_candidates} candidates. Output exactly {num\_candidates} JSON lines.

### A.2. Experiment Details

#### A.2.1. Dataset.

To comprehensively evaluate AgenticGEO, we conduct experiments across three datasets characterized by distinct content distributions and optimization goals:

-   •

    GEO-Bench (In-Domain): This serves as our primary dataset for training the evolver and critic, as well as for in-domain evaluation. Constructed from real-world Google Search results, it covers a wide spectrum of domains (e.g., Science, History, Health) with varying query difficulties. The content primarily consists of long-form articles, providing rich context for learning diverse optimization strategies.

-   •

    MS MARCO (Out-of-Domain): To assess zero-shot transferability, we employ the MS MARCO Passage Ranking dataset. Derived from Bing search logs, this dataset comprises real user queries paired with short, often unstructured text passages. Evaluating on this dataset tests whether our optimization policy can generalize to short-text scenarios and unseen query distributions without re-training.

-   •

    E-commerce (Vertical Domain): Representing a specific vertical application, this dataset is sourced from Amazon product descriptions and reviews. The optimization goal here shifts from informational retrieval to commercial visibility. This dataset challenges the agent to adapt to entity-centric content and the specific structural preferences of product-related queries.


Table 5. Dataset statistics after preprocessing. Following the GEO-Bench protocol, each query is paired with 55 documents.

Dataset

#Queries

#Docs

Avg. Content Tokens

GEO-Bench

1000

5,000

980.61

MS-Marco

1000

5,000

91.91

E-commerce

416

2,180

1,459.69

Table [5](#A1.T5 "Table 5 ‣ A.2.1. Dataset. ‣ A.2. Experiment Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") reports the key statistics of the three datasets. Following the GEO-Bench protocol, we standardize the retrieval context by pairing each query with five documents, ensuring a consistent document budget across datasets for fair comparison.

#### A.2.2. Baselines.

1\. Static Heuristics (GEO-Bench). We implement the nine official strategies from GEO-Bench (Aggarwal et al., [2024](#bib.bib2)), covering lexical, stylistic, and evidence-based modifications:

-   •

    No Optimization: The original, unmodified source content serves as the control group.

-   •

    Keyword Stuffing: Naively injects query keywords repeatedly to increase term frequency.

-   •

    Unique Words: Inserts rare vocabulary to artificially increase information entropy.

-   •

    Easy-To-Understand: Simplifies sentence structures to improve readability for general audiences.

-   •

    Authoritative: Adopts a confident and professional tone to mimic expert knowledge.

-   •

    Technical Words: Injects domain-specific jargon assuming engines prefer specialized vocabulary.

-   •

    Fluency Optimization: Polishes the text for grammatical correctness without adding information.

-   •

    Cite Sources: Injects plausible citations to external authorities to enhance credibility.

-   •

    Quotation Addition: Embeds direct quotes from relevant entities to support claims.

-   •

    Statistics Addition: Enriches the text with quantitative data points relevant to the query.


2\. State-of-the-Art.

-   •

    AutoGEO (Wu et al., [2025](#bib.bib55)): A representative automated framework that distills generative engine preferences from LLM-generated explanations into static rewriting rules. To reimplement the method, we use the GEO-Bench training dataset on the generative engine of Qwen2.5-32B-Instruct following the source code of AutoGEO.


3\. Supervised Fine-Tuning (SFT). To compare with learning-to-rewrite baselines, we fine-tune a rewriter on supervised pairs (where the target rewrites are selected based on overall score), targeting a single heuristic style, yielding controllable specialized rewriters:

-   •

    Cite Sources-SFT: Fine-tunes a rewriter to produce citation-enriched rewrites in the style of Cite Sources.

-   •

    Quotation Addition-SFT: Fine-tunes a rewriter to add concise supporting quotations in the style of Quotation Addition.

-   •

    Statistics Addition-SFT: Fine-tunes a rewriter to insert relevant numeric statements in the style of Statistics Addition.


#### A.2.3. Hyper Parameters

Table 6. Key hyperparameters of AgenticGEO (values left blank).

Module

Param.

Description

Value

Offline Critic Alignment

Loss weight

λ\\lambda

Weight in Ltotal\=Lpair+λ​LregL\_{\\text{total}}=L\_{\\text{pair}}+\\lambda L\_{\\text{reg}}

0.2

Warm-up steps

SfreezeS\_{\\text{freeze}}

Epochs with frozen backbone before unfreezing

1

Online Co-Evolution (Selection & Budget)

Iterations

TT

Total online evolution iterations

100

Exploit size

KtopK\_{\\text{top}}

Top-KtopK\_{\\text{top}} selected by critic

4

Explore size

KrandK\_{\\text{rand}}

Randomly sampled strategies per iteration

4

Evolver Learning (Sibling-Aware AWR)

Sibling coeff.

αsib\\alpha\_{\\text{sib}}

Strength of sibling-aware baseline

0.8

AWR temperature

β\\beta

Temperature in exp⁡(A/β)\\exp(A/\\beta) weighting

1.0

Archive Maintenance (MAP-Elites & Gates)

PND weight

λpnd\\lambda\_{\\text{pnd}}

Weight of novelty/diversity term in SPNDS\_{\\text{PND}}

0.3

Cell capacity

KcK\_{c}

Max items stored per archive cell

3

Implementation

LR (critic)

ηc\\eta\_{c}

Learning rate for critic fine-tuning

0.001

LR (evolver)

ηe\\eta\_{e}

Learning rate for evolver fine-tuning

0.0002

Batch size

BB

Batch size for fine-tuning

2

LoRA rank

rr

LoRA rank

16

LoRA scaling

αlora\\alpha\_{\\text{lora}}

LoRA scaling factor

32

LoRA dropout

plorap\_{\\text{lora}}

LoRA dropout

0.05

Epochs

EE

Fine-tuning epochs

2

Key hyperparameters are in Table [6](#A1.T6 "Table 6 ‣ A.2.3. Hyper Parameters ‣ A.2. Experiment Details ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization").

### A.3. Theoretical Analysis

To establish the bound, we make the standard assumptions for online convex optimization:

1.  (1)

    Boundedness & Lipschitz Continuity: The true risk function ℛ​(⋅)\\mathcal{R}(\\cdot) and the critic 𝒞t​(⋅)\\mathcal{C}\_{t}(\\cdot) are bounded in \[0,B\]\[0,B\] and are LL\-Lipschitz continuous with respect to the strategy parameters.

2.  (2)

    Critic Generalization: The critic is trained on an accumulating dataset ℬt\\mathcal{B}\_{t}.


###### Lemma A.1 (Linear Growth of Replay Buffer).

Let K\=|𝒮_select_(t)|K=|\\mathcal{S}\_{\\emph{select}}^{(t)}| denote the constant number of candidate strategies selected for ground-truth evaluation at iteration tt. Assume that each candidate strategy has an independent success probability pp. Only successful strategies will be added to the replay buffer ℬT\\mathcal{B}\_{T}. For any 0<δ<10<\\delta<1, with probility at least 1−δ1-\\delta, the size of the replay buffer can be bounded by:

(23)

||ℬT|p​K​T−1|≤log⁡(2δ)3​p​K​T\\big|\\frac{|\\mathcal{B}\_{T}|}{pKT}-1\\big|\\leq\\sqrt{\\frac{\\log(\\frac{2}{\\delta})}{3pKT}}

###### Proof.

Let Xt,iX\_{t,i} be an indicator random variable representing the success of the ii\-th candidate strategy at iteration tt, where t∈{1,…,T}t\\in\\{1,\\dots,T\\} and i∈{1,…,K}i\\in\\{1,\\dots,K\\}. By assumption, Xt,iX\_{t,i} are i.i.d. Bernoulli variables with parameter pp. The replay buffer size can be written as

(24)

|ℬT|\=∑t\=1T∑i\=1KXt,i.|\\mathcal{B}\_{T}|=\\sum\_{t=1}^{T}\\sum\_{i=1}^{K}X\_{t,i}.

Hence, the expected size of the buffer is:

(25)

μ:=𝔼​\[|ℬ​T|\]\=∑t\=1T∑i\=1K𝔼​\[Xt,i\]\=T⋅K⋅p.\\mu:=\\mathbb{E}\[|\\mathcal{B}T|\]=\\sum\_{t=1}^{T}\\sum\_{i=1}^{K}\\mathbb{E}\[X\_{t,i}\]=T\\cdot K\\cdot p.

By the standard Chernoff bound, for any ϵ∈(0,1)\\epsilon\\in(0,1),

(26)

ℙ​(||ℬT|−μ|≥ϵ​μ)≤2​e−ϵ2​μ3.\\mathbb{P}\\big(\\big||\\mathcal{B}\_{T}|-\\mu\\big|\\geq\\epsilon\\mu\\big)\\leq 2e^{-\\frac{\\epsilon^{2}\\mu}{3}}.

Setting the right-hand side equal to δ\\delta and solving for ϵ\\epsilon yields

(27)

ϵ\=3​log⁡(2δ)μ\\epsilon=\\sqrt{\\frac{3\\log(\\frac{2}{\\delta})}{\\mu}}

Substituting μ\=p​K​T\\mu=pKT, we have

(28)

ℙ​(||ℬT|p​K​T−1|≥3​log⁡(2δ)μ)≤δ.\\mathbb{P}\\big(\\big|\\frac{|\\mathcal{B}\_{T}|}{pKT}-1\\big|\\geq\\sqrt{\\frac{3\\log(\\frac{2}{\\delta})}{\\mu}}\\big)\\leq\\delta.

∎

###### Lemma A.2 (Critic Generalization Bound).

Suppose the critic is learned from the replay buffer ℬT\\mathcal{B}\_{T}, and the hypothesis class ℱ\\mathcal{F} has bounded Rademacher complexity. Under the assumption of Lemma [A.1](#A1.Thmtheorem1 "Lemma A.1 (Linear Growth of Replay Buffer). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization"), for any δ∈(0,1)\\delta\\in(0,1), with probability at least 1−δ1-\\delta,

(29)

|𝒞T​(s)−ℛ​(s)|≤1T​(2​Mℱ​2p​K+B​log⁡(2/δ)p​K)|\\mathcal{C}\_{T}(s)-\\mathcal{R}(s)|\\leq\\frac{1}{\\sqrt{T}}\\left(2M\_{\\mathcal{F}}\\sqrt{\\frac{2}{pK}}+B\\sqrt{\\frac{\\log(2/\\delta)}{pK}}\\right)

###### Proof.

The universal convergence bound states that with probability at least 1−δ21-\\frac{\\delta}{2}, the generalization error is bounded by

(30)

|𝒞T​(s)−ℛ​(s)|≤2​ℜ|ℬT|​(ℱ)+B​log⁡(2/δ)2​|ℬT|.|\\mathcal{C}\_{T}(s)-\\mathcal{R}(s)|\\leq 2\\mathfrak{R}\_{|\\mathcal{B}\_{T}|}(\\mathcal{F})+B\\sqrt{\\frac{\\log(2/\\delta)}{2|\\mathcal{B}\_{T}|}}.

where ℜ|ℬT|≤Mℱ|ℬT|\\mathfrak{R}\_{|\\mathcal{B}\_{T}|}\\leq\\frac{M\_{\\mathcal{F}}}{|\\mathcal{B}\_{T}|} is the Rademacher complexity. From Lemma [A.1](#A1.Thmtheorem1 "Lemma A.1 (Linear Growth of Replay Buffer). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization"), with probability at least 1−δ21-\\frac{\\delta}{2}, the buffer size

(31)

|ℬT|≥(1−ϵT)​p​K​T|\\mathcal{B}\_{T}|\\geq(1-\\epsilon\_{T})pKT

Substitute into the above generalization bound, we have with probability at least 1−δ1-\\delta

(32)

|𝒞T​(s)−ℛ​(s)|\\displaystyle|\\mathcal{C}\_{T}(s)-\\mathcal{R}(s)|

≤1T⋅11−ϵT​(2​Mℱ​1p​K+B​log⁡(2/δ)2​p​K)\\displaystyle\\leq\\frac{1}{\\sqrt{T}}\\cdot\\frac{1}{\\sqrt{1-\\epsilon\_{T}}}\\left(2M\_{\\mathcal{F}}\\sqrt{\\frac{1}{pK}}+B\\sqrt{\\frac{\\log(2/\\delta)}{2pK}}\\right)

For sufficiently large TT such that T≥8​log⁡(2/δ)p​K,T\\geq\\frac{8\\log(2/\\delta)}{pK}, we have ϵT≤12\\epsilon\_{T}\\leq\\frac{1}{2}. Then we will have

|𝒞T​(s)−ℛ​(s)|\\displaystyle|\\mathcal{C}\_{T}(s)-\\mathcal{R}(s)|

≤1T⋅11−12​(2​Mℱ​1p​K+B​log⁡(2/δ)2​p​K)\\displaystyle\\leq\\frac{1}{\\sqrt{T}}\\cdot\\frac{1}{\\sqrt{1-\\frac{1}{2}}}\\left(2M\_{\\mathcal{F}}\\sqrt{\\frac{1}{pK}}+B\\sqrt{\\frac{\\log(2/\\delta)}{2pK}}\\right)

\=1T​(2​Mℱ​2p​K+B​log⁡(2/δ)p​K)\\displaystyle=\\frac{1}{\\sqrt{T}}\\left(2M\_{\\mathcal{F}}\\sqrt{\\frac{2}{pK}}+B\\sqrt{\\frac{\\log(2/\\delta)}{pK}}\\right)

This bound implies that the approximation error converges as 𝒪​(1T)\\mathcal{O}(\\frac{1}{\\sqrt{T}}). ∎

###### Lemma A.3 (Evolver Regret Bound).

Let 𝒞t:𝒮→ℝ\\mathcal{C}\_{t}:\\mathcal{S}\\to\\mathbb{R} denote the risk predicted by the critic at iteration tt. Assume that 𝒞t\\mathcal{C}\_{t} is convex and LL\-Lipschitz continuous over the strategy space 𝒮\\mathcal{S} with diameter DD. Suppose the Evolver updates the strategy sts\_{t} via a gradient-based update with step size η\\eta. Then, for any comparator strategy s∗∈𝒮s^{\\ast}\\in\\mathcal{S}, the cumulative regret with respect to the critic’s predictions satisfies

(33)

∑t\=1T(𝒞t​(st)−𝒞t​(s∗))≤D​L​T\=𝒪​(T),\\sum\_{t=1}^{T}\\bigl(\\mathcal{C}\_{t}(s\_{t})-\\mathcal{C}\_{t}(s^{\\ast})\\bigr)\\;\\leq\\;DL\\sqrt{T}\\;=\\;\\mathcal{O}(\\sqrt{T}),

provided that the step size is chosen as η\=DL​T\\eta=\\tfrac{D}{L\\sqrt{T}}.

###### Proof.

The evolver updates the strategy with gradient-based approach:

(34)

st+1\=st−η​gt,where​gt\=∇𝒞t​(st).s\_{t+1}=s\_{t}-\\eta g\_{t},\\qquad\\text{where}\\ g\_{t}=\\nabla\\mathcal{C}\_{t}(s\_{t}).

For any s∗s^{\\ast}, we have

(35)

‖st+1−s∗‖2≤‖(st−η​gt)−s∗‖2.\\|s\_{t+1}-s^{\\ast}\\|^{2}\\leq\\|(s\_{t}-\\eta g\_{t})-s^{\\ast}\\|^{2}.

We expand the RHS:

(36)

‖st−η​gt−s∗‖2\=‖st−s∗‖2−2​η​⟨gt,st−s∗⟩+η2​‖gt‖2\\|s\_{t}-\\eta g\_{t}-s^{\\ast}\\|^{2}=\\|s\_{t}-s^{\\ast}\\|^{2}-2\\eta\\langle g\_{t},s\_{t}-s^{\\ast}\\rangle+\\eta^{2}\\|g\_{t}\\|^{2}

Rearranging this inequality:

(37)

2​η​⟨gt,st−s∗⟩≤‖st−s∗‖2−‖st+1−s∗‖2+η2​‖gt‖22\\eta\\langle g\_{t},s\_{t}-s^{\\ast}\\rangle\\leq\\|s\_{t}-s^{\\ast}\\|^{2}-\\|s\_{t+1}-s^{\\ast}\\|^{2}+\\eta^{2}\\|g\_{t}\\|^{2}

Dividing by 2​η2\\eta, we obtain

(38)

⟨gt,st−s∗⟩≤12​η​(‖st−s∗‖2−‖st+1−s∗‖2)+η2​‖gt‖2\\langle g\_{t},s\_{t}-s^{\\ast}\\rangle\\leq\\frac{1}{2\\eta}\\left(\\|s\_{t}-s^{\\ast}\\|^{2}-\\|s\_{t+1}-s^{\\ast}\\|^{2}\\right)+\\frac{\\eta}{2}\\|g\_{t}\\|^{2}

From the first-order inequality, we have

(39)

𝒞t​(st)−𝒞t​(s∗)≤⟨gt,st−s∗⟩\\mathcal{C}\_{t}(s\_{t})-\\mathcal{C}\_{t}(s^{\\ast})\\leq\\langle g\_{t},s\_{t}-s^{\\ast}\\rangle

Combining and Eq ([38](#A1.E38 "In Proof. ‣ Lemma A.3 (Evolver Regret Bound). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")) and Eq ([39](#A1.E39 "In Proof. ‣ Lemma A.3 (Evolver Regret Bound). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")), we sum from t\=1t=1 to TT:

∑t\=1T𝒞t​(st)−𝒞t​(s∗)≤∑t\=1T⟨gt,st−s∗⟩\\displaystyle\\sum\_{t=1}^{T}\\mathcal{C}\_{t}(s\_{t})-\\mathcal{C}\_{t}(s^{\\ast})\\leq\\sum\_{t=1}^{T}\\langle g\_{t},s\_{t}-s^{\\ast}\\rangle

≤12​η​∑t\=1T(‖st−s∗‖2−‖st+1−s∗‖2)+η2​∑t\=1T‖gt‖2\\displaystyle\\qquad\\leq\\frac{1}{2\\eta}\\sum\_{t=1}^{T}\\left(\\|s\_{t}-s^{\\ast}\\|^{2}-\\|s\_{t+1}-s^{\\ast}\\|^{2}\\right)+\\frac{\\eta}{2}\\sum\_{t=1}^{T}\\|g\_{t}\\|^{2}

For the first term,

(40)

∑t\=1T(‖st−s∗‖2−‖st+1−s∗‖2)\=‖s1−s∗‖2−‖sT+1−s∗‖2≤‖s1−s∗‖2\\sum\_{t=1}^{T}\\left(\\|s\_{t}-s^{\\ast}\\|^{2}-\\|s\_{t+1}-s^{\\ast}\\|^{2}\\right)=\\|s\_{1}-s^{\\ast}\\|^{2}-\\|s\_{T+1}-s^{\\ast}\\|^{2}\\leq\\|s\_{1}-s^{\\ast}\\|^{2}

Note that the strategy space have a diameter of DD such that the distance ‖s1−s∗‖2≤D2\\|s\_{1}-s^{\\ast}\\|^{2}\\leq D^{2}. Furthermore, since 𝒞t\\mathcal{C}\_{t} is LL\-Lipschitz, the norm of the gradient is bounded by ‖gt‖≤L\\|g\_{t}\\|\\leq L. Thus,

(41)

∑t\=1T⟨gt,st−s∗⟩≤D22​η+η2​∑t\=1TL2\=D22​η+η​T​L22\\sum\_{t=1}^{T}\\langle g\_{t},s\_{t}-s^{\\ast}\\rangle\\leq\\frac{D^{2}}{2\\eta}+\\frac{\\eta}{2}\\sum\_{t=1}^{T}L^{2}=\\frac{D^{2}}{2\\eta}+\\frac{\\eta TL^{2}}{2}

When the step size η\=DL​T\\eta=\\frac{D}{L\\sqrt{T}}, the regret can be bounded by

(42)

∑t\=1T(𝒞t​(st)−𝒞t​(s∗))≤D​L​T2+D​L​T2\=D​L​T\\sum\_{t=1}^{T}\\bigl(\\mathcal{C}\_{t}(s\_{t})-\\mathcal{C}\_{t}(s^{\\ast})\\bigr)\\leq\\frac{DL\\sqrt{T}}{2}+\\frac{DL\\sqrt{T}}{2}=DL\\sqrt{T}

Completing the proof. ∎

###### Theorem A.4 (Regret Bound for AgenticGEO Co-Evolution).

Let st∈𝒮s\_{t}\\in\\mathcal{S} denote the strategy selected at iteration tt, and let s∗∈𝒮s^{\\ast}\\in\\mathcal{S} be an optimal strategy with respect to the true environment reward ℛ\\mathcal{R}. Define the cumulative regret after TT iterations as

(43)

RT\=∑t\=1T(ℛ​(st)−ℛ​(s∗)).R\_{T}\\;=\\;\\sum\_{t=1}^{T}\\bigl(\\mathcal{R}(s\_{t})-\\mathcal{R}(s^{\\ast})\\bigr).

Under the assumptions of linear replay buffer growth (Lemma [A.1](#A1.Thmtheorem1 "Lemma A.1 (Linear Growth of Replay Buffer). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")), critic generalization (Lemma [A.2](#A1.Thmtheorem2 "Lemma A.2 (Critic Generalization Bound). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")), and sublinear evolver regret with respect to the critic predictions (Lemma [A.3](#A1.Thmtheorem3 "Lemma A.3 (Evolver Regret Bound). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")), the cumulative regret satisfies

(44)

RT\=𝒪​(T).R\_{T}\\;=\\;\\mathcal{O}(\\sqrt{T}).

![Refer to caption](2603.20213v1/x8.png)

Figure 8. Qualitative case studies of AgenticGEO. For each query-content pair, we show the original content, the optimized rewrite, and the activated strategy sequence selected by critic-guided planning.

Consequently, the average regret vanishes,

RTT→ 0as ​T→∞,\\frac{R\_{T}}{T}\\;\\to\\;0\\quad\\text{as }T\\to\\infty,

implying that the co-evolutionary AgenticGEO process asymptotically converges to an optimal strategy s∗s^{\\ast}.

###### Proof.

We first decompose the instantaneous risk gap at each time step tt as

ℛ​(st)−ℛ​(s∗)≤|ℛ​(st)−𝒞t​(st)|+|𝒞t​(st)−𝒞t​(s∗)|+|𝒞t​(s∗)−ℛ​(s∗)|\\mathcal{R}(s\_{t})-\\mathcal{R}(s^{\\ast})\\leq|\\mathcal{R}(s\_{t})-\\mathcal{C}\_{t}(s\_{t})|+|\\mathcal{C}\_{t}(s\_{t})-\\mathcal{C}\_{t}(s^{\\ast})|+|\\mathcal{C}\_{t}(s^{\\ast})-\\mathcal{R}(s^{\\ast})|

Given a replay buffer that grows linearly, the approximation and generalization errors of the critic model can be derived from Lemma [A.2](#A1.Thmtheorem2 "Lemma A.2 (Critic Generalization Bound). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization")

(45)

|ℛ​(s)−𝒞t​(s)|\=𝒪​(1t).|\\mathcal{R}(s)-\\mathcal{C}\_{t}(s)|=\\mathcal{O}(\\frac{1}{\\sqrt{t}}).

Similarly, the evolver’s regret can be derived from Lemma [A.3](#A1.Thmtheorem3 "Lemma A.3 (Evolver Regret Bound). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") as

(46)

|𝒞t​(st)−𝒞t​(s∗)|\=𝒪​(1t).|\\mathcal{C}\_{t}(s\_{t})-\\mathcal{C}\_{t}(s^{\\ast})|=\\mathcal{O}(\\frac{1}{\\sqrt{t}}).

Combining above and summing over the time horizon TT, we can conclude that the cumulative regret is

∑t\=1Tℛ​(st)−ℛ​(s∗)\=∑t\=1T𝒪​(1t)\=𝒪​(T).\\sum\_{t=1}^{T}\\mathcal{R}(s\_{t})-\\mathcal{R}(s^{\\ast})=\\sum\_{t=1}^{T}\\mathcal{O}(\\frac{1}{\\sqrt{t}})=\\mathcal{O}(\\sqrt{T}).

∎

### A.4. Case Study

Figure [8](#A1.F8 "Figure 8 ‣ Theorem A.4 (Regret Bound for AgenticGEO Co-Evolution). ‣ A.3. Theoretical Analysis ‣ Appendix A Supplementary Information ‣ AgenticGEO: A Self-Evolving Agentic System for Generative Engine Optimization") shows three representative optimization trajectories across distinct domains. AgenticGEO selects content-conditioned strategy sequences that systematically increase factual grounding and information density. For GMO, it adds authoritative citations and concrete statistics. For the subtropical rainforest, it injects precise climate measurements and domain-specific terms. For book recommendations, it leverages social proof by synthesizing platform reviews. These examples illustrate how the archive and critic enable adaptive multi-step edits beyond any single fixed heuristic.