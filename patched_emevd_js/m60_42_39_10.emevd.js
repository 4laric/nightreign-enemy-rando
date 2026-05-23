// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    RegisterBonfire(1029101950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1029101950, 1029100950);
    RegisterBonfire(1029101951, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1029101951, 1029100951);
    $InitializeCommonEvent(0, 90015400, 1029100800, 1029100200, 1029100201, 1039100201, 1039100206, 1028100201, 0, 1029100204);
    $InitializeCommonEvent(0, 90015401, 1029100800, 1029100200, 1029100201, 1029100204, 1029100203, 1029102902, 0);
    $InitializeCommonEvent(0, 90015402, 1029102902, 1029100201, 1039100802);
    $InitializeCommonEvent(0, 90015403, 1029102902, 1029100201, 1039100802);
    $InitializeCommonEvent(0, 90015404, 1029100800, 1029100201, 0, 1039100802);
    $InitializeCommonEvent(0, 90015405, 1029100202, 1029100201);
    $InitializeCommonEvent(0, 90015406, 1029100201, 1039100802, 1029100800, 1029102902, 30, 904503600, 0, 1029100202);
    $InitializeCommonEvent(0, 90015407, 0, 1029100201, 1029100800, 1029100800, 1020, 920310, 11200, 904503600, 1029100202);
    $InitializeCommonEvent(0, 90015031, 1029100201, 1029100800, 1029102902, 30, 920310, 1029100202);
    $InitializeCommonEvent(0, 9005810, 1029100800, 1029100500, 1029101500, 5);
    $InitializeCommonEvent(0, 90015005, 1029101500, 1029102800, 1029100800);
    $InitializeCommonEvent(0, 90015000, 0, 1029100820, 905810000, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1029100820, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1029100820, 30, 931010, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1029100820, 1029100820, 1020, 931010, 11290, 905810000, 1029100820);
    $InitializeCommonEvent(0, 9005810, 1029100820, 1029100520, 1029101520, 5);
    $InitializeCommonEvent(0, 90015005, 1029101520, 1029102820, 1029100820);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 1029100820, 931010, 1029100820, 0, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1029100820);
    $InitializeCommonEvent(0, 90015016, 1029100820);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1029100820);
        $InitializeCommonEvent(0, 90015468, 1029100820, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1029100820, 25, 0, 1029102820, 72463, 1029102820);
    $InitializeCommonEvent(0, 90015041, 0, 0, 0, 72495);
    if (MissionActive(802)) {
        $InitializeCommonEvent(0, 90085020, 802, 8506, 8507, 8505, 1029100280, 99850, 1029100280, Hero.Executor);
        $InitializeCommonEvent(0, 90085021, 802, 8506, 1029102280, 1029100280, Hero.Executor);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90085002, 802, 8507, 8506, 1029100280, 1029105280, 1029100281, 0, 0, 0, 20032);
        }
        if (2 == 1) {
            $InitializeCommonEvent(0, 90085002, 802, 8507, 8506, 1029100280, 1029105280, 1029100281, 1029100282, 0, 0, 20032);
        }
        if (3 == 1) {
            $InitializeCommonEvent(0, 90085002, 802, 8507, 8506, 1029100280, 1029105280, 1029100281, 1029100282, 1029100283, 0, 20032);
        }
        if (4 == 1) {
            $InitializeCommonEvent(0, 90085002, 802, 8507, 8506, 1029100280, 1029105280, 1029100281, 1029100282, 1029100283, 1029100284, 20032);
        }
        $InitializeCommonEvent(0, 90085016, 802, 8507, 8506, 1029100280, 1029105280, 1020, 3);
        $InitializeCommonEvent(0, 90085022, 802, 8507, 1029102281, 1029100280, 505, Hero.Executor);
        $InitializeCommonEvent(0, 90085023, 802, 8507, 8505, 1029100280, 9000, 1029100280, Hero.Executor);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90015000, 8506, 1029100281, 912000070, 30, 0, 8507);
            $InitializeCommonEvent(0, 99055500, 1029100281, 15);
        }
        if (1 != 1) {
            $InitializeCommonEvent(0, 90015000, 8506, 1029105280, 912000070, 30, 0, 8507);
            $InitializeCommonEvent(0, 99055500, 1029105280, 15);
        }
        $InitializeCommonEvent(0, 90015030, 0, 1029105280, 30, 920630, 8507);
    }
    $InitializeCommonEvent(0, 90085032, 802, 1029106280);
    $InitializeCommonEvent(0, 90015150, 1029100290, 73081);
    $InitializeCommonEvent(0, 90015151, 1029100290, 73041);
    $InitializeCommonEvent(0, 90015152, 1029100290, 73041);
    $InitializeCommonEvent(0, 90015150, 1029100291, 73082);
    $InitializeCommonEvent(0, 90015151, 1029100291, 73042);
    $InitializeCommonEvent(0, 90015152, 1029100291, 73042);
    $InitializeEvent(0, 1029102910);
});

$Event(1029102800, Restart, function(chrEntityId, chrEntityId2, animationId, areaEntityId) {
    EnableNetworkSync();
    EndIf(EventFlag(1039102900));
    DisableCharacterCollision(chrEntityId);
    DisableCharacter(chrEntityId);
    DisableCharacterAI(chrEntityId);
    WaitFor(InArea(20000, areaEntityId));
    SetEventFlagID(1029102905, ON);
    EndIf(CharacterDead(chrEntityId2));
    EndIf(EventFlag(1039102800));
    if (!(!EventFlag(1028102905) && !EventFlag(1039102915))) {
        WaitFor(EventFlag(1028102905) || EventFlag(1039102915));
        WaitFor(EventFlag(1028102802) || EventFlag(1039102812));
    }
L0:
    WaitFixedTimeSeconds(2);
    ForceAnimationPlayback(chrEntityId, animationId, false, false, false);
    EnableCharacterCollision(chrEntityId);
    EnableCharacter(chrEntityId);
    EnableCharacterAI(chrEntityId);
    CreateReferredDamagePair(chrEntityId, 1039100802);
    WaitFor(CharacterHasSpEffect(chrEntityId, 10279));
    SetEventFlagID(1029102800, ON);
    SetEventFlagID(1029102803, ON);
    EndEvent();
});

$Event(1029102810, Default, function(chrEntityId) {
    EnableNetworkSync();
    EndIf(EventFlag(chrEntityId));
    WaitFor(EventFlag(1029102800));
    if (!CharacterAIState(chrEntityId, AIStateType.Combat)) {
        WaitFor(!AllPlayersInArea(1029102902));
    }
L0:
    WaitFor(
        CharacterAIState(chrEntityId, AIStateType.Combat, NotEqual, 1)
            || EventFlag(1039102905)
            || EventFlag(9193));
    SetNetworkconnectedEventFlagID(1029102801, ON);
    EndEvent();
});

$Event(1029102820, Default, function(chrEntityId) {
    EndIf(EventFlag(1039102900));
    WaitFor(EventFlag(1029102801) || EventFlag(9193));
    SetSpEffect(chrEntityId, 10260);
    WaitFor(CharacterHasSpEffect(chrEntityId, 10278));
    ChangeWeather(Weather.None, -1, false);
    ClearSpEffect(20000, 4213);
    SetEventFlagID(1029102802, ON);
    SetEventFlagID(1029102803, OFF);
    EndEvent();
});

$Event(1029102830, Default, function(chrEntityId) {
    EnableNetworkSync();
    EndIf(EventFlag(1039102900));
    WaitFor(EventFlag(1029102802));
    DisableCharacterCollision(chrEntityId);
    DisableCharacter(chrEntityId);
    DisableCharacterAI(chrEntityId);
    EndEvent();
});

$Event(1029102840, Default, function(chrEntityId) {
    EndIf(EventFlag(chrEntityId));
    WaitFor(CharacterHPValue(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    PlaySE(chrEntityId, SoundType.SFX, 888880000);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, 1039100802, 0, 0);
    DisplayTextEffectId(1000);
    SetEventFlagID(chrEntityId, ON);
});

$Event(1029102850, Default, function(areaEntityId, chrEntityId) {
    if (!EventFlag(1029102802)) {
        if (!EventFlag(1039102900)) {
            area = InArea(20000, areaEntityId);
            cond = EventFlag(1029102802);
            WaitFor(area);
            EndIf(CharacterDead(chrEntityId) || EventFlag(1029102802));
            EndIf(EventFlag(1039102800) || EventFlag(1029102800) || EventFlag(9193));
            ChangeWeather(Weather.Type81, -1, false);
            WaitFixedTimeSeconds(3);
            SetSpEffect(20000, 4213);
            WaitFor(!InArea(20000, areaEntityId));
            ChangeWeather(Weather.None, -1, false);
            WaitFixedTimeSeconds(3);
            ClearSpEffect(20000, 4213);
            RestartEvent();
        }
    }
L0:
    EndEvent();
});

$Event(1029102860, Default, function(chrEntityId, areaEntityId) {
    WaitFor(CharacterDead(chrEntityId) && InArea(20000, areaEntityId));
    ChangeWeather(Weather.None, -1, false);
    WaitFixedTimeSeconds(3);
    ClearSpEffect(20000, 4213);
    EndEvent();
});

$Event(1029102870, Default, function() {
    WaitFor(EventFlag(1029102802));
    ChangeWeather(Weather.None, -1, false);
    WaitFixedTimeSeconds(3);
    ClearSpEffect(20000, 4213);
    EndEvent();
});

$Event(1029102880, Default, function(chrEntityId, areaEntityId) {
    DisableNetworkSync();
    WaitFor(EventFlag(7601) && InArea(20000, areaEntityId));
    if (!CharacterDead(chrEntityId)) {
        if (!EventFlag(1028100900)) {
            if (!EventFlag(1039100801)) {
                if (!(EventFlag(1039102905) || EventFlag(1029102802))) {
                    SetSpEffect(20000, 99110);
                    WaitFixedTimeSeconds(1);
                    RestartEvent();
                }
            }
        }
    }
L0:
    EndEvent();
});

$Event(1029102890, Default, function(chrEntityId, nameId, chrEntityId2) {
    DisableNetworkSync();
    if (!EventFlag(1029100800)) {
        if (!EventFlag(1039102800)) {
            WaitFor(EventFlag(1029102800) && CharacterAIState(chrEntityId2, AIStateType.Combat));
            if (!EventFlag(1029100800)) {
                if (!EventFlag(1039102800)) {
                    if (!EventFlag(1029102801)) {
                        DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
                        if (!EventFlag(72450)) {
                            SetNetworkconnectedEventFlagID(72450, ON);
                        }
                        WaitFor(
                            EventFlag(1029102801)
                                && CharacterAIState(chrEntityId2, AIStateType.Combat, NotEqual, 1));
                        DisplayBossHealthBar(Disabled, chrEntityId, 0, nameId);
                        RestartEvent();
                    }
                }
            }
        }
    }
L0:
    EndEvent();
});

$Event(1029102900, Default, function() {
    WaitFor(CharacterHPValue(1039100802) <= 0 && CharacterAIState(1029100800, AIStateType.Combat));
    ForceCharacterDeath(1029100800, true);
});

$Event(1029102910, Default, function() {
    DisableNetworkSync();
    EndIf(EventFlag(9193));
    CreateAssetfollowingSFX(1029101510, 90, 807037);
    DisableObjAct(1029101510, 99096);
    WaitFor(ActionButtonInArea(4311, 1029101510));
    DisplayTextEffectId(2200);
    SetEventFlagID(9193, ON);
    SetNetworkconnectedEventFlagID(8185, ON);
    DeleteAssetfollowingSFX(1029101510, true);
});

$Event(1029102995, Restart, function() {
    CreateReferredDamagePair(1029100800, 1039100802);
});
