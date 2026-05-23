// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 9005810, 46800800, 46800950, 46801950, 5);
    $InitializeCommonEvent(0, 90015005, 46801950, 46800950, 46800800);
    $InitializeCommonEvent(0, 90045006, 46800200, 46800201, 46800202, 0);
    $InitializeCommonEvent(0, 90045000, 46800200, 46801200, 0, 904980600);
    $InitializeCommonEvent(0, 90045001, 46800800, 46800201, 0, 46800800, 46801210, 1);
    $InitializeCommonEvent(0, 90045002, 46800800, 0, 46800800, 46800800, 1020, 11241, 904980600, 46800800);
    $InitializeCommonEvent(0, 90045004, 46800200, 46800202, 46800800, 46800290, 46800291, 46800292, 0, 46800800);
    $InitializeCommonEvent(0, 90045005, 46800201, 46800202, 46800800, 46801210, 0, 46800290, 46800291);
    $InitializeCommonEvent(0, 90015000, 46800201, 46800800, 904980600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46800800, 15);
    $InitializeCommonEvent(0, 90015030, 46800201, 46800800, 30, 921100, 0);
    $InitializeCommonEvent(0, 90015009, 46800201, 46801200, 0, 2);
    $InitializeCommonEvent(0, 90045006, 46800200, 46800201, 46800202, 1);
    $InitializeCommonEvent(0, 90045000, 46800200, 46801200, 1, 904510601);
    $InitializeCommonEvent(0, 90045001, 46800800, 46800201, 1, 46800810, 46801210, 1);
    $InitializeCommonEvent(0, 90045002, 46800800, 1, 46800810, 46800810, 1020, 11241, 904510601, 46800810);
    $InitializeCommonEvent(0, 90045004, 46800200, 46800202, 46800800, 46800290, 46800291, 46800292, 1, 46800810);
    $InitializeCommonEvent(0, 90045005, 46800201, 46800202, 46800800, 46801210, 1, 46800290, 46800291);
    $InitializeCommonEvent(0, 90015000, 46800201, 46800810, 904510601, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46800810, 15);
    $InitializeCommonEvent(0, 90015030, 46800201, 46800810, 30, 921100, 0);
    $InitializeCommonEvent(0, 90015009, 46800201, 46801200, 1, 2);
    $InitializeCommonEvent(0, 90045006, 46800200, 46800201, 46800202, 2);
    $InitializeCommonEvent(0, 90045000, 46800200, 46801200, 2, 903575000);
    $InitializeCommonEvent(0, 90045001, 46800800, 46800201, 2, 46805800, 46801210, 1);
    $InitializeCommonEvent(0, 90045002, 46800800, 2, 46805800, 46800820, 1020, 11241, 903575000, 46800950);
    $InitializeCommonEvent(0, 90045004, 46800200, 46800202, 46800800, 46800290, 46800291, 46800292, 2, 46805800);
    $InitializeCommonEvent(0, 90045005, 46800201, 46800202, 46800800, 46801210, 2, 46800290, 46800291);
    $InitializeCommonEvent(0, 90015000, 46800201, 46800820, 903560000, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46800820, 15);
    $InitializeCommonEvent(0, 90015000, 46800201, 46800821, 903570000, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46800821, 15);
    $InitializeCommonEvent(0, 90015030, 46800201, 46805800, 30, 921100, 0);
    $InitializeCommonEvent(0, 90015009, 46800201, 46801200, 2, 2);
    if (IsPlayMode(2)) {
        if (IsMapVariation(0)) {
            $InitializeCommonEvent(0, 90015042, 0, 46800200);
        }
        if (IsMapVariation(1)) {
            $InitializeCommonEvent(0, 90015042, 10, 46800200);
        }
        if (IsMapVariation(2)) {
            $InitializeCommonEvent(0, 90015042, 20, 46800200);
        }
    }
});

$Event(46802200, Default, function() {
    EndIf(EventFlag(46802201));
    actFlag = ActionButtonInArea(9231, 46801200) || EventFlag(46800200) || EventFlag(46800201);
    item = PlayerHasItem(ItemType.Goods, 8000);
    WaitFor(actFlag);
    GotoIf(L2, !item.Passed);
    GotoIf(L0, IsMapVariation(0));
    GotoIf(L1, IsMapVariation(1));
    WaitFixedTimeSeconds(1);
    RestartEvent();
L2:
    DisplayGenericDialog(308000, PromptType.OKCANCEL, NumberofOptions.NoButtons, 46801200, 1);
    WaitFixedTimeSeconds(1);
    RestartEvent();
L0:
    RemoveItemFromPlayer(ItemType.Goods, 8000, 1);
    SetNetworkconnectedEventFlagID(46800200, ON);
    SetNetworkconnectedEventFlagID(46802201, ON);
    RecordUserDispLog(10103, 46801200, LogObjectType.NpcName, 904980600);
    EndEvent();
L1:
    RemoveItemFromPlayer(ItemType.Goods, 8000, 1);
    SetNetworkconnectedEventFlagID(46800201, ON);
    SetNetworkconnectedEventFlagID(46802201, ON);
    RecordUserDispLog(10103, 46801200, LogObjectType.NpcName, 904510601);
    EndEvent();
});

$Event(46802800, Restart, function(chrEntityId) {
    if (!EventFlag(46802830)) {
        DisableCharacter(chrEntityId);
        DisableCharacterAI(chrEntityId);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    ForceAnimationPlayback(46801210, 0, true, false, false);
    EndEvent();
});

$Event(46802801, Restart, function() {
    if (!EventFlag(46802830)) {
    }
L0:
    EndEvent();
});

$Event(46802810, Restart, function(chrEntityId, chrEntityId2, sfxId, dummypolyId) {
    if (!EventFlag(46802830)) {
        WaitFor(EventFlag(46800200));
        ForceAnimationPlayback(46801210, 0, true, false, false);
        WaitFixedTimeSeconds(2);
        SpawnOneshotSFX(TargetEntityType.Character, chrEntityId, dummypolyId, sfxId);
        SetSpEffect(chrEntityId2, 0);
        WaitFixedTimeSeconds(1.5);
        EnableCharacter(chrEntityId);
        EnableCharacterAI(chrEntityId);
        SetFieldBattleBGMHeatUp(28, false);
        EndEvent();
    }
L0:
    EndEvent();
L1:
    WaitFixedTimeFrames(1);
    ForceAnimationPlayback(46801210, 0, true, false, false);
    EnableCharacter(chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetFieldBattleBGMHeatUp(28, false);
    EndEvent();
});

$Event(46802811, Restart, function(chrEntityId, nameId) {
    DisableNetworkSync();
    if (!EventFlag(46802830)) {
        WaitFor(EventFlag(46802810) && EntityInRadiusOfEntity(20000, chrEntityId, 50, 1));
        DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
        WaitFor(EventFlag(46802810) && !EntityInRadiusOfEntity(20000, chrEntityId, 50, 1));
        DisplayBossHealthBar(Disabled, chrEntityId, 0, nameId);
        RestartEvent();
    }
L0:
    EndEvent();
});

$Event(46802820, Restart, function() {
    if (!EventFlag(46802830)) {
        WaitFor(EventFlag(46802810));
        SetSpEffect(0, 0);
    }
L0:
    EndEvent();
});

$Event(46802830, Restart, function(chrEntityId, nameId) {
    WaitFor(!EventFlag(46802830) && EventFlag(46802820) && CharacterHPValue(chrEntityId) <= 0);
    PlaySE(chrEntityId, SoundType.SFX, 888880000);
    HandleMinibossDefeat(chrEntityId);
    DisplayBossHealthBar(Disabled, chrEntityId, 0, nameId);
    WaitFixedTimeSeconds(5);
    SetNetworkconnectedEventFlagID(chrEntityId, ON);
});

$Event(46802840, Default, function() {
    WaitFor(!EventFlag(46802840) && EventFlag(46802830) && EventFlag(46804590));
    ClearSpEffect(0, 0);
});

$Event(46802900, Restart, function(chrEntityId) {
    if (!EventFlag(46802930)) {
        DisableCharacter(chrEntityId);
        DisableCharacterAI(chrEntityId);
        ForceAnimationPlayback(chrEntityId, 30025, true, false, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    ForceAnimationPlayback(46801210, 0, true, false, false);
    EndEvent();
});

$Event(46802901, Restart, function() {
    if (!EventFlag(46802930)) {
    }
L0:
    EndEvent();
});

$Event(46802910, Restart, function(chrEntityId, chrEntityId2, chrEntityId3, chrEntityId4) {
    GotoIf(L0, EventFlag(46802930));
    GotoIf(L1, EventFlag(46802910));
    WaitFor(EventFlag(46800201));
    ForceAnimationPlayback(chrEntityId, 20025, true, false, false);
    SetSpEffect(chrEntityId2, 0);
    SetSpEffect(chrEntityId4, 0);
    SetSpEffect(chrEntityId3, 0);
    EnableCharacter(chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetFieldBattleBGMHeatUp(28, false);
    EndEvent();
L0:
    EndEvent();
L1:
    WaitFixedTimeFrames(1);
    ForceAnimationPlayback(46801210, 0, true, false, false);
    EnableCharacter(chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetFieldBattleBGMHeatUp(28, false);
    EndEvent();
});

$Event(46802911, Restart, function(chrEntityId, nameId) {
    DisableNetworkSync();
    if (!EventFlag(46802930)) {
        WaitFor(EventFlag(46802910) && EntityInRadiusOfEntity(20000, chrEntityId, 50, 1));
        DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
        WaitFor(EventFlag(46802910) && !EntityInRadiusOfEntity(20000, chrEntityId, 50, 1));
        DisplayBossHealthBar(Disabled, chrEntityId, 0, nameId);
        RestartEvent();
    }
L0:
    EndEvent();
});

$Event(46802920, Restart, function() {
    if (!EventFlag(46802930)) {
        WaitFor(EventFlag(46802910));
        SetSpEffect(0, 0);
    }
L0:
    EndEvent();
});

$Event(46802930, Restart, function(chrEntityId, nameId) {
    WaitFor(!EventFlag(46802930) && EventFlag(46802920) && CharacterHPValue(chrEntityId) <= 0);
    PlaySE(chrEntityId, SoundType.SFX, 888880000);
    HandleMinibossDefeat(chrEntityId);
    DisplayBossHealthBar(Disabled, chrEntityId, 0, nameId);
    WaitFixedTimeSeconds(5);
    SetNetworkconnectedEventFlagID(chrEntityId, ON);
});

$Event(46802940, Default, function() {
    WaitFor(!EventFlag(46802940) && EventFlag(46802930) && EventFlag(46804590));
    ClearSpEffect(0, 0);
});
