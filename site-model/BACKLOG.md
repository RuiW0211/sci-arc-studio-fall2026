# Y-1 场地模型：待办 / 细化备忘录

最后更新：2026-10-08（切换到 Houdini 后整理：已完成的项划掉并注明怎么完成的；只适用于 Blender 版的项标为“Blender 版，已停用”；新增第 11 节）。每一项写明：要做什么、用什么数据、现状。
旧的 Blender 版项目归档在 `RuiW0211/sci-arc-studio-fall2026-blender`，文中提到的 `site-model/scripts/`、`data/`、`exports/context.glb` 都在那里。
优先级：⭐⭐⭐ 影响网页上的识别度或数据正确性｜⭐⭐ 明显提升｜⭐ 锦上添花

---

## 0. 项目愿景（暂定，2026-10-05 Rui 提出）

> 点云上的每一个点、每一组点，都连着我们的 research。它们可以编辑、可以移动，会随着我们在 Angels Knoll 坡地上做的建筑而变化。引起变化的不只是占地、光照这些物理因素，还有政治、经济、民生。

这一节是方向，不是待办。下面各节的具体任务都朝这个方向走。

### 0.1 知识层：点击任意点，看到相关的 research
- **目标**：在 LiDAR · Linked 里点一个点，弹出和它相关的 research、新闻、摘要。
- **“相关”可以挂在不同层级**，从细到粗，每一级的信息都能被下一级继承：
  1. **单个物体**：一栋楼、一棵树、MOCA、Angels Flight（用的是现有的物体 ID，例如 `BLD_<id>`、`Tree_042`）；
  2. **地块**：Y-1 及周边地块（APN）。法律、产权、开发历史大多挂在这一层；
  3. **区域或主题组**：例如 “Bunker Hill 再开发区”、“Grand Ave 文化走廊”、“Metro 站影响范围”；
  4. **整个场地**：时间线、Stakeholder Register、综述。
- **内容从哪里来**：本地已有的 research 文件，`Visiting Studio` 文件夹里有：
  - `Y-1_Key_Findings_Summary`、`Y-1_1_Seven_Insights`、`Y-1_2_Strategic_Brief`、`Y-1_3_Validation_Protocol`；
  - `Stakeholder_Register`、`Angels_Knoll_Historical_Proposals_Research`、`Y-1_V2_Complete_Research`；
  - EIR 第 II 章（`D_II`）；
  - 以及记忆里记下的 MOCA / SLA 法律更正（Gov Code 54227(a) 等）。
- **数据结构设想**：每条知识是一个独立文件（Markdown + 头部字段），写明它挂在哪里（物体 ID / APN / 区域 / 主题）、类型（research / 新闻 / 摘要 / 法规 / 时间线事件）、日期、出处链接。网页按点的物体标签和位置，查出所有相关条目并显示。
  - 这样组员不用懂代码，写一个 Markdown 文件就能新增一条知识。
- **要先决定**：
  1. 哪些 research 可以放进**公开的 repo**？有些内部分析可能只适合在课程里分享；
  2. 新闻只放摘要和链接，不全文转载（版权）；
  3. 每条摘要要标明出处和日期，事实性内容要能追溯到原始来源。

### 0.2 可编辑层：点可以编辑、可以移动
- **目标**：点云不只是“看”的，而是可以被设计改变的。
- **已经有的基础**：每个 LiDAR 点都知道自己属于哪个物体（第 8 节第 1 步，已完成）；按物体替换点的方案（第 8 节第 3、4 步）已经规划好。
- **往前走的方向**：
  1. 在 Blender 里加入设计方案（放在 `Design` 等 collection）→ 方案范围内的点被替换、移除或移动（例如被新建筑占据的树和地形点）；
  2. 多个方案并存（`Option_A`、`Option_B`），可以在网页上切换、对比；
  3. 点的“变化”有动画：从现状过渡到方案，让人看到变化本身。

### 0.3 影响层：变化由多种因素驱动
- **目标**：点的变化不只是几何上的替换，还反映设计带来的影响。
- **物理因素**（可以计算）：
  - 占地和地形改变：挖填方、被移除的树；
  - 光照和阴影：新建筑在不同季节、不同时刻投下的阴影，覆盖了哪些点；
  - 视线：哪些点被遮挡，哪些景观被挡住；
  - 也许还有：风、热岛、排水。
- **非物理因素**（需要数据和明确的规则）：
  - **政治 / 法规**：Surplus Land Act 程序、分区和容积率、诉讼状态、公共审批节点；
  - **经济**：地价、租金、公共投资与私人开发的比例、税收；
  - **民生**：可负担住房的数量、公共空间的可达性、周边居民和商户受到的影响（例如流离失所的风险）。
- **怎么在点云上表达**：每种因素作为点的一个**属性**（这正是第 8 节“扩展属性”设计的用途），再通过颜色、大小、透明度、位移或动画显示出来。例如：
  - 被阴影覆盖时间越长的点越暗；
  - 公共可达性越低的点越透明；
  - 受租金压力影响大的周边街区，点会“下沉”或变色。
- **要特别谨慎的地方**：
  1. 非物理因素没有唯一的“正确算法”。每条规则都要**写明假设、数据来源和计算方式**，并且在网页上能看到，不能做成黑箱；
  2. 可视化很容易被误读，这和课程网站 t-SNE 页第 8 节“诚实地解读”是同一个问题。点的移动是**示意性的表达，不是预测**，网页上要说清楚；
  3. 需要可信的数据来源，例如 Census ACS、LA City / County Open Data、Assessor 的估值、可负担住房的统计。

### 0.4 大致的推进顺序（以后再细化）
1. **知识层先做物体和地块两级**：内容用现有的 research，点击就能看到。这一步最快能看到效果，也能先把内容的组织方式定下来；
2. **时间线和区域 / 主题组**：把历史提案（1960 年代至今）和法律节点放到空间里；
3. **设计方案进入点云**（第 8 节第 3、4 步）：多方案切换和对比；
4. **物理影响**：占地、阴影、视线，可以计算，规则也比较明确；
5. **非物理影响**：先选一两个有数据支撑的指标（例如可负担住房数量、公共空间可达性），把规则、数据和可视化都做透明，再逐步扩展。

### 0.5 还没想清楚、要和组员讨论的
- “一组点”（group）的定义：按物体、按地块、按区域，还是可以自由框选？
- 知识的作者和审核：谁来写？谁来确认内容准确？
- 非物理因素的指标选哪些？权重由谁决定？要不要让观看者自己调整？
- 这个网页最终给谁看：评图老师、社区、开发方、公众？这会影响内容的深度和语气（参考课程网站的三档阅读深度）。

---

## 1. 树木

- [ ] ⭐⭐⭐ **加入树种资料**
  - 数据：`references/AngelsLanding_IS-2_TreeInventory.pdf`，第 15–44 页是逐棵树的表格，有编号、树种、胸径 DBH、高度、树冠，第 14 页是位置图（KPFF Design Survey 底图）。
  - 做法：
    1. 把位置图对位到模型坐标（用地块边界和街角做控制点，方法和 `georef_plotplan.py` 一样）；
    2. 把清单上的树和 LiDAR 识别出的树按距离配对（`data/trees.json`）；
    3. 配上的树用清单里的树种，没配上的保留 LiDAR 结果。
  - 现状：229 棵树全部是同一种“椭球树冠 + 树干”。
- [ ] ⭐⭐ （Blender 版，已停用：网页不再用 mesh）**按树种做不同的树形**：棕榈（细高的树干 + 一簇顶冠）、阔叶乔木、灌木。每种做一个共享网格，GLB 不会变大。
- [ ] ⭐⭐ **核对数量差异**：LiDAR 在 951 地块里识别出 90 棵，2018 年清单约 128 棵。逐棵对照后，区分是漏识别（树冠重叠、低于 3 m）还是树已经不在了。
- [x] ~~⭐ 识别加密区以外的树（现在只做了 Y-1 周边约 184 × 178 m）。~~ （2026-10-07 完成，Houdini：整个 1.4 km 场地约 11,000 棵树，每棵一个物体）
- [ ] ⭐ （Blender 版，已停用）识别并去掉 MOCA 屋顶露台上那几丛植物在屋顶网格上形成的鼓包，或者换成树。

## 2. MOCA

> 这一节是 Blender 版 mesh 的细化。2026-10-08 起网页只显示点云，这些项暂停；以后要做实体模型时再看。

- [ ] ⭐⭐ **材质分区**：红砂岩体块、绿色立方体、筒形拱顶（金属屋面）、金字塔天窗。现在整栋是一种红色。参考 `references/moca/archeyes_64.jpg`。
- [ ] ⭐⭐ **把筒形拱顶和南侧约 10 条采光脊拟合成干净的几何体**，方法同金字塔，代码在 `prep_moca.py`。现在它们还是 0.5 m 栅格表面，近看会粗糙。
- [ ] ⭐ 入口拱门通道、立面上的窗。
- [ ] ⭐ 下沉庭院和地下展厅（LiDAR 看不到，要找剖面图）。
- 已知：ArchEyes 上标为 “MOCA floor plan” 的那张图应该是 California Plaza，不是 MOCA，不要拿来用。

## 3. Metro Pershing Square 西北出入口

> 这一节是 Blender 版 mesh 的细化。2026-10-08 起网页只显示点云，这些项暂停；以后要做实体模型时再看。

- [ ] ⭐⭐ **扶梯朝向**：现在假设是从北端往南下，需要照片或 Metro 的图纸确认。
- [ ] ⭐⭐ **桅杆高度和位置**：现在按你给的那张照片估计为约 10 m；短柱的位置也是估的。最好再找一张从北侧或正侧面拍的照片。
- [ ] ⭐ 雨棚的玻璃百叶（照片里是一排排的条形玻璃）。
- [ ] ⭐ 电梯出入口（SubwayNut 的照片里有花岗岩方盒和电梯，位置还没确认）。

## 4. Angels Flight

> 这一节是 Blender 版 mesh 的细化。2026-10-08 起网页只显示点云，这些项暂停；以后要做实体模型时再看。

- [ ] ⭐⭐ **车厢 Olivet / Sinai 和上下站的真实尺寸**。现在是估的。可以从 HAER/HABS（Library of Congress）、Angels Flight 官网或 1996 年重建的资料里找。
- [ ] ⭐ 车厢的配色（橙 + 黑）、分级车厢的台阶形外形、下站 Beaux-Arts 拱门的细节。
- [ ] ⭐ 轨道中段的错车段（测绘图上能看到三组轨道线）。
- [ ] ⭐ 用 LiDAR 做一个横剖面，再核对一次轨道的水平位置，现在估计误差在 1–2 m 以内。

## 5. 地形与场地细节

- [ ] ⭐⭐ **从 Wood Plot Plan 提取更多现状要素**。它是矢量图，已经对位好了（`data/plotplan_georef.json`）。可以提取：沿 Hill St 的楼梯、挡土墙、小路、出入口周边的阶梯花坛。
- [ ] ⭐ 人行道和路缘石的高差（现在路面和人行道是连在一起的地形）。
- [ ] ⭐ 围栏（场地从 2013 年起就围起来了，对讲“场地现状”很重要）。

## 6. 周边建筑

- [ ] ⭐⭐ （Blender 版，已停用：网页不再用 mesh）**重要邻居单独精修**：Grand Central Market、Bradbury Building、Two California Plaza、Omni Hotel、Colburn School。现在都是 LiDAR 分层体块。
- [ ] ⭐ （Blender 版，已停用）8 栋合并后还有少量问题边的建筑（不影响观看，网页要做剖切时才需要修）。
- [x] ~~⭐ 扩大范围，把 The Broad、Walt Disney Concert Hall 纳入（你的描述里提到它们，但在现在的 800 m 范围外）。需要再下载一块 LiDAR 瓦片。~~ （2026-10-06 完成：下载 9 块 LiDAR 瓦片，Houdini 处理 1.4 km 范围，The Broad 和 Disney Hall 都在里面）
- [ ] ⭐ 部分 LARIAC 轮廓是 2008 年的，和 2023 年 LiDAR 对不上的地方（中位误差 0.7 m，57 栋误差超过 5 m），要逐栋核查。

## 7. 数据与地块

- [ ] ⭐⭐⭐ **确认 Y-1 的正式范围**：951 是 95,419 sqft，加上 952 是 96,012 sqft，EIR 写的是 97,631 sqft。要确认 952 算不算进去，或者 EIR 用的是另一份测量。
- [ ] ⭐⭐ 叠加 ZIMAS 的分区、容积率和高度限制，作为网页上的信息图层。
- [ ] ⭐ 地块信息弹窗的内容，可以接你现有的 Y-1 研究资料：时间线、法规、Stakeholder Register。

## 8. 网页查看器（下一个大阶段）

**显示模式路线图**
- 现阶段：**四种模式并行**，按“来源 + 变体”命名，一键切换，相机保持不动（2026-10-05 定）：
  ```
  MODEL   [ Mesh ] [ Points ]
  LIDAR   [ Raw  ] [ Linked ]
  ```
  1. **Model · Mesh**：Blender 模型；
  2. **Model · Points**：网页加载时从同一份 GLB 实时撒点生成，mesh 一改就自动同步；
  3. **LiDAR · Raw**：2023 年 USGS 实测点云，**保持未经处理的原始参照**。只有高度、分类、强度三种着色，没有 Layers 面板，点击也不识别物体；
  4. **LiDAR · Linked**：同一批 LiDAR 点贴上 Blender 物体标签，按图层统一着色，图层开关生效，点击识别物体并高亮。配色（2026-10-05 由 Rui 选定）来自 Coolors 的流行配色 `F0EAD2 · DDE5B6 · ADC178 · A98467 · 6C584C`：地形深褐 `#6C584C`、建筑奶油 `#F0EAD2`、树橄榄绿 `#ADC178`、Landmarks 浅褐 `#A98467`、Design 浅绿 `#DDE5B6`。其他 `#3A302A` 是从地形色调暗得来的，不在原配色里。高亮改为品红 `#FF3EA5`（Rui 选定）。之前的黄色 `#F0E442` 和橄榄绿的树同属黄绿色系；试过亮青蓝 `#3FC8FF` 和珊瑚红 `#FF6B4A` 后，选了品红。点地形只显示信息、不高亮（`"highlight": false`）。颜色在 `web/config.json` 里改。
  - 已知取舍：Landmarks 的浅褐不如之前的朱红醒目，这套配色也没有专门做色盲验证。之前用过的 Okabe-Ito（色盲友好）色值留作备选：地形 `#8F8A80`、建筑 `#56B4E9`、树 `#009E73`、Landmarks `#D55E00`、Design `#CC79A7`、其他 `#3F3F3F`。
  - 以后“按物体替换”的功能都做在 Linked 里，Raw 始终保持原样。代码里的模式 ID 仍然是 `mesh / points / lidar / linked`。
- **2026-10-06 改为两种模式**（Rui 决定，分支 `rui/houdini-lidar-laz`）：`[ Mesh ] [ Point cloud ]`。
  - Model · Points 删除。
  - Raw 并入 Point cloud：点云扩大并按距离抽稀以后，Raw 已不再是“每个原始点”，和 Linked 用的是同一份数据。所以改成在 Color 里切换 Layer（原 Linked）、Height、Ground / other、Intensity（原 Raw）；任何上色下图层开关和点选都可用。
  - 模式 ID 改为 `mesh / cloud`；旧的 `linked` / `lidar` 仍可识别（分别对应按图层、按高度上色）。
- **2026-10-08 只保留 Point cloud**（Rui 决定，切换到 Houdini）：网页不再用 mesh，Mode 栏先隐藏；组员的设计 `design_<名字>.glb` 叠在点云上显示。
- 目标（以后优化成两种模式）（Blender 时期的设想）：
  1. **较写实的 Blender mesh**：地形贴 NAIP 航拍图，PBR 材质，光照烘焙；
  2. **高精度点云，而且要能和 mesh 同步修改更新**。
- [ ] ⭐⭐⭐ **“按物体切分的 LiDAR 点云”方案**（实现目标 2；2026-10-05 取代原来按区域整块替换的“编辑区”方案）
  核心思路：以真实 LiDAR 为底，只在 Blender 里改动过的物体上用 mesh 替换。点云模式默认就有 LiDAR 的精细度，同时能跟着 Blender 更新。
  1. [x] ~~（2026-10-05 完成：`lidar_labels.py`，9.9M 点 4.5 s；归不进物体的 `_other` 占 13%，主要是加密区外的树和车辆）**给每个 LiDAR 点贴物体标签**：物体名和 Blender 一致（`BLD_<id>`、`Tree_042`、`MOCA`、`AF_*`、`Metro_*`、`Terrain`）。按优先级判断：Landmarks → 树冠 → 建筑轮廓 → 地面。归不进任何物体的点（车、路灯等）标为 `_other`。标签也是点云的第一个扩展属性。网页上的图层开关同样作用于 LiDAR 点，点击 LiDAR 点可以看到它属于哪个物体。~~ 2026-10-07 起由 Houdini 重做：2.1 万个物体（建筑、树、灌木、车辆、墙），名称规则见 CLAUDE.md。
  2. [x] ~~**全密度 + 分层加载**：现在网页每 3 个点取 1 个（330 万）。改用 COPC 或 Potree，显示 800 m 范围内全部约 1,000 万个点，近处多加载、远处少加载。~~（2026-10-07 完成，没有用 COPC：Y-1 周边 250 m 内保留全部点，往外按物体逐渐抽稀，一共 885 万个点，存成一个 44 MB 的 LAZ；浏览器里按屏幕上的点密度加载）
  3. [ ] （Blender 版，已停用：现在组员的设计是独立的 `design_<名字>.glb`，叠在点云上）**几何指纹 + 自动替换**：一键导出时记录每个物体的几何指纹（geometry hash），和上一次比对：
     - 新建的物体 → 从 mesh 撒点加入；
     - 删除的物体 → 删掉它的 LiDAR 点；
     - 修改过的物体 → 删掉原来的点，换成从新 mesh 撒的点；
     - 没动过的物体 → 保留真实 LiDAR 点。
  4. [ ] **模拟 LiDAR 风格的撒点**：从上方“打”虚拟激光，加测量噪声，约 15 点/m²，让新旧点混在一起看不出接缝。
  5. [ ] **接入现场采集**：以后 Y-1 现场用手机 LiDAR 或照片生成的点云 / Splat，作为同样带标签的图层叠加进来，补上航测看不到的立面、树下和挡土墙细部。
  - 背景：Poisson 实验（`site-model/experiments/`）证明航测 LiDAR 不适合整体直接转 mesh。树会熔成一片，建筑只剩屋顶皮，被遮挡的地方是破洞。所以要按物体分别处理。
- [x] ~~⭐⭐⭐ **点云格式要支持扩展属性**（来自课程网站 t-SNE 页第 10 节 feature-field splatting 的思路）：~~ （2026-10-07 完成：LAZ 的 extra bytes 里有 `object`、`segment`、`hag` 三个属性，`lidar_points.json` 描述每个属性；以后加属性不用改格式）
  - 每个点除了 xyz，还要能带任意数量的属性：分类、强度、来源（`lidar` / `mesh_sampled` / `edited`）、物体 ID（例如 `MOCA`、`AF_Track_Deck`、`Tree_042`，和 Blender 的物体名对应）、所属地块 APN、材质。
  - 以后加入的 CLIP/SAM 语义特征、t-SNE 聚类编号，也只是多加一个属性，格式不用改。
  - 网页的“着色模式”统一做成“选一个属性 → 映射成颜色”，新增属性就自动多一个模式。
  - 做法：属性用独立的二进制通道（每个属性一个文件或 COPC 的 extra bytes），另外用一个 `attributes.json` 描述每个属性的名称、类型和取值范围。现在的 `web/data/lidar_points.bin` 是固定的 8 字节记录，正式版要改成这种结构。
- [ ] ⭐⭐ **用模型给 feature splat 当“真值”**：以后给 Y-1 拍照训练 LangSplat 或 Feature 3DGS 时，把 splat 对位到场地坐标系，用 Blender 里的物体 ID（建筑、树、挡土墙、Metro 雨棚）去检验 splat 的语义聚类对不对。这正是 t-SNE 页建议的练习，我们多了一份逐个物体的标注。
- [ ] ⭐ 网页内容做三档阅读深度（参照课程网站的 Research / Student / ELI5），视觉风格和课程网站保持一致。
- [ ] ⭐ splat 图层的格式先保留接口，等选定方法再定。新方法（例如 2025 年的 Student Splatting and Scooping）常见查看器不一定支持。
- [ ] ⭐⭐ 点云着色：用 NAIP 航拍图（公有领域）给 LiDAR 点取真实颜色（这批 LiDAR 没有 RGB）。
- [x] ~~⭐⭐ 点云变大（不抽稀、扩大范围）后改用 COPC 或 Potree 的分层加载格式；超过 100 MB 的文件放外部存储。~~ （2026-10-07 完成：用 LAZ + 浏览器端的分层显示代替，44 MB，不需要外部存储）
- [x] ~~⭐⭐⭐ three.js 加载 `exports/context.glb`（需要 DRACOLoader）。~~ （2026-10-05 完成，Blender 版；2026-10-08 起网页只显示点云和组员的设计 GLB）
- [x] ~~⭐⭐⭐ 图层开关：地形、建筑、树、地块、Landmarks。~~ （2026-10-05 完成；现在的图层来自 Houdini 的点云分类）
- [ ] ⭐⭐ 预设视角：4th & Hill 路口、Angels Flight 上站、Grand Ave、俯视平面。
- [x] ~~⭐⭐ 点击地块或建筑弹出信息。GLB 里已经带了 `apn`、`height_m`、`source` 等属性（glTF extras）。~~ （2026-10-08 完成：浮动标签，显示建筑名称、地址、县里地块数据，Shift 多选）
- [ ] ⭐ 剖切或切片，用来看坡地的高差。
- [ ] ⭐ 测距和高差测量。

## 9. 工程化

**Blender 更新 → 网页同步（做 Site model viewer 时一起完成，之后要定期检查）**
- [x] ~~⭐⭐⭐ **手动建模放在独立的 collection 里**：`Terrain`、`Buildings`、`Y1_Parcel`、`Landmarks`、`Trees` 是脚本生成的，重新运行 build 脚本时会被清空重建，在里面手改的东西会丢失。设计方案、手动精修的建筑放在新的 collection 里（例如 `Design`），脚本永远不碰它们。
  - 检查：每次重新运行 build 脚本前，确认手动内容不在上面这 5 个 collection 里。~~（2026-10-05 完成，Blender 版；Houdini 版的对应做法是每人一个设计场景，见 `site-model/houdini/README.md`）
- [x] ~~⭐⭐⭐ **一键导出脚本**（`site-model/scripts/export_glb.py`，在 Blender 里运行）：把脚本生成的 collection 加上 `Design` 等手动 collection 一起导出到 `site-model/exports/context.glb`，导出设置固定（Draco 压缩、+Y Up、带 extras 属性），不用每次手动选。
  - 检查：新增的手动 collection 要能被导出；导出后在本地查看器里核对。~~（2026-10-05 完成，Blender 版；Houdini 版是设计场景里的 `/out/export_design`）
- [x] ~~⭐⭐⭐ **GLB 只放一个位置**：GLB 存在 `site-model/exports/`，但 GitHub Pages 只发布 `web/`。修改 `.github/workflows/pages.yml`，部署时自动把 `site-model/exports/*.glb` 复制进发布的网页里，repo 里只保留一份 GLB。
  - 检查：合并 PR 后，线上网页加载的是最新的 GLB（看浏览器 Network 面板里 GLB 的请求和大小）。~~（2026-10-05 完成；现在用于组员的 `design_<名字>.glb`）

- [x] ~~⭐⭐⭐ **建 git repo**，加 `README.md` 和 `CLAUDE.md`，写清朋友协作的规则：开分支、发 PR、不直接推到 main。~~（2026-10-05 完成：`RuiW0211/sci-arc-studio-fall2026`；2026-10-08 换成 Houdini 版的新项目，旧的改名为 `sci-arc-studio-fall2026-blender` 并归档）
- [x] ~~⭐⭐⭐ 邀请组员之前，在 GitHub 上打开 main 分支保护（必须通过 PR 才能合并）。~~ （2026-10-05 完成：main 分支保护 + CODEOWNERS，必须由 owner 批准）
- [x] ~~⭐⭐ **一键重建脚本**：依次运行 `fetch_data → lidar_dsm → lidar_tiers → prep_moca → prep_blender → prep_landmarks → prep_trees`，然后在 Blender 里运行 `build_blender → build_landmarks → build_trees`，再导出 GLB。~~ （2026-10-05 完成，Blender 版：`build_all_blender.py`；Houdini 版的顺序见 `site-model/houdini/README.md`）
- [x] ~~⭐⭐ `requirements.txt`：laspy[lazrs]、pymupdf、rasterio、shapely、pyproj、scipy、scikit-learn。laspy 和 pymupdf 目前是用 `pip --user` 装的。~~ （2026-10-05 完成；2026-10-08 改成 Houdini 流程需要的包）
- [x] ~~⭐⭐ **大文件处理**：LAZ（67 MB）、各种 PDF 不放进 git，写一个下载脚本代替。GLB 目前 1.25 MB，可以直接放进 repo。~~ （2026-10-05 完成：原始 LAZ 用下载脚本，`.gitignore` 排除 PDF 和参考资料）
- [x] ~~⭐ GitHub Pages 部署。~~ （2026-10-05 完成）

## 10. 远期

- [ ] ⭐⭐ **现场拍照生成 Gaussian Splat**：把 Y-1 核心区换成照片级效果。用场地上的固定物（Angels Flight 下站、Metro 桅杆、街角）做对位控制点。
- [ ] ⭐ Google Earth Studio 做网页开场的飞入视频（必须标注 Google 来源，不能从中提取 3D）。

## 11. Houdini（2026-10-05 起）

- [ ] ⭐⭐⭐ **未归类的点**：Y-1 周边 250 m 内还有约 2.5 万个 `_other` 点（原来 6.7 万），多是立面、低矮杂物和树下的点。
- [ ] ⭐⭐⭐ **人流图层在 Houdini 数据上重做**（Rui）：Clark 的版本在旧项目（PR #9）。新数据已经准备好：`site-model/houdini/handoff/`（建筑体块带名称、地址、用途，加地形）。
- [ ] ⭐⭐ **自动实体的名字**：部分自动生成的名字有重复字，例如 “Building on Government Parcel parcel”（`tools/auto_entities.py`）。
- [ ] ⭐⭐ **核心区以外的地标正式名称**：现在 83 个手工确认的实体都在 250 m 内（含 35 个地标名），之外的 1,051 个是按县里地块自动生成的。
- [ ] ⭐⭐ **Mac 上走一遍安装教程**：`docs/SETUP.md` 第 6–7 节（Houdini、Houdini MCP）还没有在 Mac 上实际跑过。
- [ ] ⭐⭐ **点的“势场”模式**（第 0 节）：每个点带研究属性，随设计变化，例如 φ = Σ wᵢfᵢ，加一个回到原位的弹簧。放在新的模式里，Point cloud 保持不变。
- [ ] ⭐ 浮动标签：眉题太长时会压到右上角的 ×；多个标签有时互相重叠。

---

## 版权提醒

`references/` 里的 EIR 附录、ArchEyes 和 SubwayNut 的图片、Getty 的照片都**只在本地当建模参考**，不能放进公开的网页或 repo。
可以公开的数据：USGS 3DEP（公有领域）、LA County GIS、OpenStreetMap（需要标注 © OpenStreetMap contributors）。
