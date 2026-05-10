# Bugfix Requirements Document

## Introduction

中间对话区域（messages.js 的 `renderMessages`）始终以纯线性列表方式渲染当前活跃路径的消息，用户切换分支后只是替换为新路径的线性消息列表，无法从对话区域本身感知到"此处存在分支"。用户需要在对话区域中直观地看到分支结构的视觉提示，而不仅仅依赖右侧的树状图面板。

此问题影响用户对分支结构的感知和导航效率——用户必须同时关注右侧面板才能了解分支位置，增加了认知负担。

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 一条消息的 child_count > 1（即该消息是分支点，有多个子分支）THEN 对话区域渲染该消息时没有任何视觉提示表明此处存在分支

1.2 WHEN 用户切换到不同分支后查看对话区域 THEN 对话区域仅显示新路径的线性消息列表，无法区分当前路径与其他可能的分支路径

1.3 WHEN 对话区域中存在分支点消息 THEN 用户无法从对话区域直接感知有多少个分支可供选择，也无法直接在对话区域中切换分支

### Expected Behavior (Correct)

2.1 WHEN 一条消息的 child_count > 1（即该消息是分支点）THEN 对话区域 SHALL 在该消息下方显示分支指示器，包含分支数量和当前所在分支的标识（如 "分支 2/3"）

2.2 WHEN 用户切换到不同分支后查看对话区域 THEN 对话区域 SHALL 在分支点处显示分支指示器，让用户清楚知道当前处于哪个分支以及总共有多少分支

2.3 WHEN 对话区域中的分支指示器被用户点击（左右箭头切换）THEN 系统 SHALL 切换到对应的兄弟分支并重新渲染对话区域为新路径的消息

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 一条消息的 child_count <= 1（即该消息不是分支点）THEN 对话区域 SHALL CONTINUE TO 以现有方式正常渲染该消息，不显示任何分支指示器

3.2 WHEN 会话没有任何分支（所有消息的 child_count <= 1）THEN 对话区域 SHALL CONTINUE TO 以纯线性列表方式渲染所有消息，与当前行为完全一致

3.3 WHEN 右侧树状图面板中用户点击节点切换分支 THEN 系统 SHALL CONTINUE TO 正常切换分支并重新渲染对话区域的消息列表

3.4 WHEN 用户右键消息行选择"从此处创建分支" THEN 系统 SHALL CONTINUE TO 正常创建分支并更新树状图

---

## Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type MessageRenderContext
  OUTPUT: boolean
  
  // Returns true when the message is a branch point (has multiple children)
  RETURN X.child_count > 1
END FUNCTION
```

```pascal
// Property: Fix Checking - Branch Point Visual Indicator
FOR ALL X WHERE isBugCondition(X) DO
  renderedRow ← renderMessages'(messages)
  branchPointRow ← findRowByNodeId(renderedRow, X.node_id)
  ASSERT branchPointRow CONTAINS branch_indicator_element
  ASSERT branch_indicator_element DISPLAYS branch_count = X.child_count
  ASSERT branch_indicator_element DISPLAYS current_branch_index
END FOR
```

```pascal
// Property: Preservation Checking - Non-branch Messages Unchanged
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT renderMessages(messages_containing_X) = renderMessages'(messages_containing_X)
END FOR
```
