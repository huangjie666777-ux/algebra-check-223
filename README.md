# 数学公式单行排版与有理式演算核验后端

将结构化公式树排版为单行、自包含的 SVG（仅含字形轮廓路径与横线矩形，
不依赖字体文件、外链、脚本或 foreignObject）。使用
fonts/STIXTwoMath-Regular.otf 的真实字形轮廓、前进宽度、斜体修正与
OpenType MATH 表度量，不做等宽估算。

/check 面向教师核对有理式演算：接收 2 至 10 步表达式树，逐步做精确有理
运算（SymPy，QQ[x]），报告每步在实数域上的禁取值，并判定相邻步骤
是否恒等、定义域是否变化；每步同时返回按原式排版的 SVG。

## 运行

    .venv/bin/uvicorn algebra_check223.app:app --port 8123

## 接口

POST /render

    {
      "font_size": 48,
      "formula": { "type": "...", ... }
    }

返回 200:

    { "svg": "<svg ...>", "width": 196.03, "height": 121.92, "baseline": 82.56 }

width / height / baseline（基线距 SVG 顶部的距离）与 font_size 同一单位。
校验失败返回 422 与 {"detail": "..."}，不交付半成品。

POST /check

    {
      "font_size": 36,
      "steps": [ <表达式树>, ... ]        # 2 至 10 步
    }

返回 200:

    {
      "steps": [
        { "svg": "...", "width": ..., "height": ..., "baseline": ...,
          "numerator": "x**2 - 4", "denominator": "x - 2",
          "forbidden": ["2"] }
      ],
      "comparisons": [
        { "step": 0,
          "relation": "identical" | "domain_changed" | "not_identical",
          "added_forbidden": [...], "removed_forbidden": [...],
          "evidence": {"polynomial": "2 - x",
                       "coefficients": ["-1", "2"]}   # 仅 not_identical
        }
      ]
    }

- forbidden 为该步表达式在实数域上的禁取值：每个原始子式除数的零点
  （含嵌套除法内层、零次幂的底数零点）精确求实根并去重；有理根写作
  整数或 n/d，无理根保留精确代数形式（如 sqrt(2)、CRootOf(...)），
  不使用浮点容差判等。恒为零的除数直接拒绝（422）。
- relation 含义：identical = 相邻两式为同一有理函数且禁取集合相同；
  domain_changed = 在公共定义域上恒等但禁取值有增删（约分抹不掉限制，
  增删值列于 added_forbidden / removed_forbidden）；not_identical =
  不恒等，附交叉乘积差多项式（num1*den2 - num2*den1）作为证据，
  不做抽样取点判定。
- 每步 SVG 按原始表达式树排版（分式、乘除、幂与必要括号原样保留），
  不会用约分或展开结果替换原式。

## 表达式节点格式（/check）

- {"type":"num","n":-3,"d":4}    有理常数 n/d；n、d 为整数，d 非零
- {"type":"var"}                 变量 x
- {"type":"add"|"sub"|"mul"|"div","left":E,"right":E}
- {"type":"pow","base":E,"exp":0..6}   exp 为 0 至 6 的整数

只接受上述结构化节点；代码或表达式字符串（如 "x+1"）一律拒绝。
每棵树至多 200 节点、深 20 层；运算过程中任一中间分子/分母次数
超过 12 即拒绝。输入树不被修改。

## 节点格式

- {"type":"text","value":"x+1"}        纯文本（仅字体覆盖的字符）
- {"type":"row","children":[...]}      横向序列，基线对齐
- {"type":"frac","num":N,"den":N}      分式，横线居中于数学轴
- {"type":"scripts","base":N,"sup":N?,"sub":N?}  上标/下标，可单独或同时出现
- {"type":"sqrt","radicand":N}         平方根，横线覆盖被开方内容
- {"type":"paren","child":N,"left":"(","right":")"}  括号包围；
  left/right 可选 ( ) [ ] { } |，默认圆括号

节点可任意组合嵌套。上下标随层级按 MATH 表 ScriptPercentScaleDown /
ScriptScriptPercentScaleDown 缩小，同现时保持最小间距并计入基字斜体修正。
括号与根号高度超出普通符号时先选伸展变体（.s1...sN），再按 GlyphAssembly
连接信息拼装伸展部件，绝不纵向拉伸完整字形。嵌套后外层尺寸自动重算，
viewBox 按全部墨迹与横线的实际包围盒计算，不发生裁切。

## 示例

    curl -X POST localhost:8123/render -H 'Content-Type: application/json' -d '{
      "font_size": 48,
      "formula": {"type":"paren","child":{"type":"row","children":[
        {"type":"scripts","base":{"type":"text","value":"x"},
                           "sup":{"type":"text","value":"2"}},
        {"type":"text","value":"+"},
        {"type":"frac","num":{"type":"text","value":"1"},
          "den":{"type":"sqrt","radicand":
            {"type":"scripts","base":{"type":"text","value":"y"},
                              "sub":{"type":"text","value":"i"}}}}
      ]}}}'

## 自测

    .venv/bin/python -m algebra_check223.selftest

## 代码结构

- algebra_check223/font.py    字体读取：度量、MATH 常量、轮廓路径、伸展变体与拼装
- algebra_check223/nodes.py   公式树校验（深度/节点数/字号/字符覆盖限制）
- algebra_check223/expr.py    表达式树校验、精确有理运算、禁取值与相邻步比较
- algebra_check223/emit.py    表达式树 -> 排版节点（保留原式结构与必要括号）
- algebra_check223/layout.py  递归布局：行、分式、上下标、根号、括号
- algebra_check223/svg.py     SVG 绘制与包围盒/基线计算
- algebra_check223/app.py     FastAPI HTTP 交付（/render 与 /check）
- algebra_check223/selftest.py 自测

## 范围与限制

- 仅处理字体覆盖的文字；不解析 LaTeX，不做换行，输出恒为单行。
- 缺字、未知节点、缺子项、非有限或非正字号、过深（>64 层）或过大
  （>5000 节点）的输入一律拒绝。
- 排版结果确定：同一输入产生完全相同的 SVG；输入树不被修改。
- /check 只做单变量 x 的有理式演算核验，不做方程求解或化简教学建议。
