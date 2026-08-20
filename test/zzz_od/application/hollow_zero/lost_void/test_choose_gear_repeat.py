"""LostVoidChooseGear 入口层重复交互快速退出测试。

背景(源码 ``lost_void_choose_gear.py``):迷失之地入口层有多个相邻NPC(蕾/奥菲莉亚/研究员),
游戏交互判定按 角度>距离,刚选完武备的NPC仍可重复交互;寻路走向旁边感叹号时容易再次命中
同一个NPC,重复打开同一个武备选择画面(整套点击识别约40秒),累计导致层间移动10分钟超时。

修复行为(已读源码确认):
- 构造时可传 ``completed_name_list``(入口层跨交互共享的已完成武备名单);列表非空时,
  ``choose_gear`` 先只点击首个武备读名字(``_get_first_gear_name``),difflib(cutoff=0.7)
  命中列表 → ``round_success('重复武备选择')`` → ``重复退出`` 节点点返回后透传该状态。
- 列表为 ``None``(层中武备选择)不做快速判断,行为与原来一致。
- ``点击携带`` 成功后把本次识别到的武备名(``recognized_name_list``)补进共享列表(去重)。

fixture:``迷失之地-武备选择/初始战术棱镜方案``(已有) 用于画面识别;武备槽位识别与
名称OCR 分别 patch ``_find_gears_with_status`` / ``_get_first_gear_name``,只测决策逻辑。
"""
from unittest.mock import Mock, patch

import pytest
from test.conftest import TestContext

from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_gear import (
    LostVoidChooseGear,
)


def _make_op(test_context: TestContext, completed_name_list: list[str] | None) -> LostVoidChooseGear:
    test_context.lost_void.load_artifact_data()
    op = LostVoidChooseGear(test_context, completed_name_list=completed_name_list)
    test_context.mock_screen('迷失之地-武备选择', '初始战术棱镜方案')
    op.screenshot()
    return op


# (已完成名单, 首个武备OCR名, 期望命中)
# difflib cutoff=0.7:同名/末字OCR错字仍命中;完全不同的武备(另一个NPC的画面)不命中
QUICK_CHECK_CASES: list[tuple[list[str], str, bool]] = [
    (['[携游]敕令玄幡'], '[携游]敕令玄幡', True),
    (['[携游]敕令玄幡', '[终结]律动节能器'], '[携游]敕令玄蟠', True),  # OCR 错一字
    (['[携游]敕令玄幡'], '[照]月魄凛光', False),  # 另一个NPC的武备画面 不命中
]


@pytest.mark.parametrize(
    'completed, first_name, expect_hit', QUICK_CHECK_CASES,
    ids=['同名命中', '错字命中', '不同画面不命中'],
)
def test_quick_check_by_first_gear_name(
    test_context: TestContext, completed: list[str], first_name: str, expect_hit: bool,
) -> None:
    """列表非空时按首个武备名快速判断:命中 → 重复武备选择;不命中 → 继续原有识别流程。"""
    op = _make_op(test_context, completed)

    with (
        patch.object(test_context.controller, 'mouse_move', create=True),
        patch.object(op, '_find_gears_with_status', return_value=([(object(), True)], object())),
        patch.object(op, '_get_first_gear_name', return_value=first_name),
        patch.object(op, 'get_gear_pos_by_click_ocr', return_value=([], [])) as mock_full_ocr,
    ):
        result = op.choose_gear()

    if expect_hit:
        assert result.is_success
        assert result.status == LostVoidChooseGear.STATUS_REPEATED
        assert not mock_full_ocr.called, '命中重复后不应再执行整套点击识别'
    else:
        # 不命中 → 走原有流程(此处 get_gear_pos_by_click_ocr 返回空 → round_retry)
        assert mock_full_ocr.called, '不命中时应继续原有识别流程'
        assert not result.is_success


def test_none_completed_list_skips_quick_check(test_context: TestContext) -> None:
    """completed_name_list 为 None(层中武备选择)时 不做快速判断。"""
    op = _make_op(test_context, None)

    with (
        patch.object(test_context.controller, 'mouse_move', create=True),
        patch.object(op, '_find_gears_with_status', return_value=([(object(), True)], object())),
        patch.object(op, '_get_first_gear_name') as mock_quick,
        patch.object(op, 'get_gear_pos_by_click_ocr', return_value=([], [])),
    ):
        op.choose_gear()

    assert not mock_quick.called, 'None 时不应执行快速判断'


def test_empty_completed_list_skips_quick_check(test_context: TestContext) -> None:
    """列表为空(入口层第一次选择)时 不做快速判断,直接走原有流程。"""
    op = _make_op(test_context, [])

    with (
        patch.object(test_context.controller, 'mouse_move', create=True),
        patch.object(op, '_find_gears_with_status', return_value=([(object(), True)], object())),
        patch.object(op, '_get_first_gear_name') as mock_quick,
        patch.object(op, 'get_gear_pos_by_click_ocr', return_value=([], [])),
    ):
        op.choose_gear()

    assert not mock_quick.called, '空列表(首次)不应执行快速判断'


def test_click_equip_commits_recognized_names(test_context: TestContext) -> None:
    """点击携带成功后 把本次识别到的武备名补进共享列表 且去重。"""
    shared: list[str] = ['[携游]敕令玄幡']
    op = LostVoidChooseGear(test_context, completed_name_list=shared)
    op.recognized_name_list = ['[携游]敕令玄幡', '[终结]律动节能器']

    success = op.round_success('按钮-携带')
    with patch.object(op, 'round_by_find_and_click_area', return_value=success):
        op.click_equip()

    assert shared == ['[携游]敕令玄幡', '[终结]律动节能器'], '应补充新名称且不重复添加'


def test_click_equip_without_shared_list(test_context: TestContext) -> None:
    """completed_name_list 为 None 时 点击携带不报错(层中武备选择场景)。"""
    op = LostVoidChooseGear(test_context, completed_name_list=None)
    op.recognized_name_list = ['[携游]敕令玄幡']

    success = op.round_success('按钮-携带')
    with patch.object(op, 'round_by_find_and_click_area', return_value=success):
        result = op.click_equip()

    assert result.is_success


def test_exit_repeated_clicks_back_and_returns_status(test_context: TestContext) -> None:
    """重复退出节点:点击返回成功后 以 重复武备选择 状态结束(供 run_level 计数)。"""
    op = LostVoidChooseGear(test_context, completed_name_list=['[携游]敕令玄幡'])

    success = op.round_success('按钮-返回')
    with patch.object(op, 'round_by_find_and_click_area', return_value=success) as mock_click:
        result = op.exit_repeated()

    assert mock_click.called
    assert result.is_success
    assert result.status == LostVoidChooseGear.STATUS_REPEATED
