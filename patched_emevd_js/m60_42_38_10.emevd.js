// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1028100281, 15);
    RegisterBonfire(1028101950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1028101950, 1028100950);
    $InitializeCommonEvent(0, 9005810, 1028100800, 1028100500, 1028101500, 5);
    $InitializeCommonEvent(0, 90015005, 1028101500, 1028102800, 1028100800);
    $InitializeCommonEvent(0, 90015000, 0, 1028100810, 904505000, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 1028100810, 15);
    $InitializeCommonEvent(0, 90015030, 0, 1028100810, 30, 920310, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 1028100810, 1028100810, 1020, 920310, 11290, 904505000, 1028100810);
    $InitializeCommonEvent(0, 9005810, 1028100810, 1028100510, 1028101510, 5);
    $InitializeCommonEvent(0, 90015005, 1028101510, 1028102810, 1028100810);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 1028100810, 920310, 1028100810, 0, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 1028100810);
    $InitializeCommonEvent(0, 90015016, 1028100810);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 1028100810);
        $InitializeCommonEvent(0, 90015468, 1028100810, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015017, 1028100810, 25, 0, 1028102810, 72442, 1028102810);
    $InitializeCommonEvent(0, 90015041, 240, 0, 0, 72473);
    $InitializeEvent(0, 1028102200, 1028105200, 1028102200);
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015021, 0, 1028105820, 903180000, 30, 0, 0, 74962);
        $InitializeCommonEvent(0, 99055500, 1028105820, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1028105820, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015021, 0, 1028105820, 903180000, 30, 0, 0, 74962);
        $InitializeCommonEvent(0, 90015030, 0, 1028105820, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1028100820, 1028105820, 1030, 940000, 11200, 903180000, 1028100520);
    $InitializeCommonEvent(0, 90015006, 1028101520, 1028100520, 1028100820, 5);
    $InitializeCommonEvent(0, 90015005, 1028101520, 1028102820, 1028100820);
    GotoIf(S2, Signed(0) != 0);
    GotoIf(S2, 0 != 0);
    Goto(S4);
S2:
    GotoIf(S3, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1028100820, 940000, 1028105820, 0, 0);
    Goto(S4);
S3:
    $InitializeCommonEvent(0, 90015008, 0, 1028100820, 940000, 1028105820, 0, 0);
S4:
    $InitializeCommonEvent(0, 90015400, 1028100800, 1028100200, 1028100201, 1039100201, 1039100206, 1029100201, 0, 1028100204);
    $InitializeCommonEvent(0, 90015401, 1028100800, 1028100200, 1028100201, 1028100204, 1028100203, 1028102900, 0);
    $InitializeCommonEvent(0, 90015402, 1028102900, 1028100201, 1039100802);
    $InitializeCommonEvent(0, 90015403, 1028102900, 1028100201, 1039100802);
    $InitializeCommonEvent(0, 90015404, 1028100800, 1028100201, 0, 1039100802);
    $InitializeCommonEvent(0, 90015405, 1028100202, 1028100201);
    $InitializeCommonEvent(0, 90015406, 1028100201, 1039100802, 1028100800, 1028102900, 30, 904503600, 0, 1028100202);
    $InitializeCommonEvent(0, 90015407, 0, 1028100201, 1028100800, 1028100800, 1020, 920310, 11200, 904503600, 1028100202);
    $InitializeCommonEvent(0, 90015031, 1028100201, 1028100800, 1028102900, 30, 920310, 1028100202);
    $InitializeCommonEvent(0, 9005810, 1028100800, 1028100500, 1028101500, 5);
    $InitializeCommonEvent(0, 90015005, 1028101500, 1028102800, 1028100800);
    $InitializeCommonEvent(0, 90015150, 1028100290, 73079);
    $InitializeCommonEvent(0, 90015151, 1028100290, 74039);
    $InitializeCommonEvent(0, 90015152, 1028100290, 74039);
    $InitializeCommonEvent(0, 90015150, 1028100291, 73080);
    $InitializeCommonEvent(0, 90015151, 1028100291, 74040);
    $InitializeCommonEvent(0, 90015152, 1028100291, 74040);
    $InitializeCommonEvent(0, 90005526, 1028100500, 1028101200);
    $InitializeEvent(0, 1028102210, 1028102350, 1028104350);
});

$Event(1028102200, Restart, function(chrEntityId, areaEntityId) {
    ClearSpEffect(chrEntityId, 4800);
    ClearSpEffect(chrEntityId, 5666);
    EndIf(EventFlag(1028100205));
    SetSpEffect(chrEntityId, 4800);
    SetSpEffect(chrEntityId, 5666);
    WaitFor(
        HasDamageType(chrEntityId, 20000, DamageType.Any)
            || EntityInRadiusOfEntity(20000, chrEntityId, 10, 1)
            || InArea(20000, areaEntityId));
    SetNetworkconnectedEventFlagID(1028100205, ON);
    ClearSpEffect(chrEntityId, 4800);
    ClearSpEffect(chrEntityId, 5666);
});

$Event(1028102800, Default, function(chrEntityId, chrEntityId2, animationId, areaEntityId) {
    EnableNetworkSync();
    EndIf(EventFlag(1028100800));
    DisableCharacterCollision(chrEntityId);
    DisableCharacter(chrEntityId);
    DisableCharacterAI(chrEntityId);
    WaitFor(InArea(20000, areaEntityId));
    SetEventFlagID(1028102905, ON);
    EndIf(CharacterDead(chrEntityId2));
    EndIf(EventFlag(1039102800));
    EndIf(EventFlag(1029102800));
    EndIf(EventFlag(1039102820));
    WaitFixedTimeSeconds(2);
    ForceAnimationPlayback(chrEntityId, animationId, false, false, false);
    EnableCharacterCollision(chrEntityId);
    EnableCharacter(chrEntityId);
    EnableCharacterAI(chrEntityId);
    CreateReferredDamagePair(chrEntityId, 1039100802);
    WaitFor(CharacterHasSpEffect(chrEntityId, 10279));
    SetEventFlagID(1028102800, ON);
    SetEventFlagID(1028102803, ON);
    EndEvent();
});

$Event(1028102805, Default, function(chrEntityId) {
    EnableNetworkSync();
    EndIf(EventFlag(chrEntityId));
    WaitFor(EventFlag(1028102800));
    if (!CharacterAIState(chrEntityId, AIStateType.Combat)) {
        WaitFor(!AllPlayersInArea(1028102900));
    }
L0:
    WaitFor(
        CharacterAIState(chrEntityId, AIStateType.Combat, NotEqual, 1)
            || EventFlag(1039102905)
            || EventFlag(1029102905)
            || EventFlag(1039102915)
            || EventFlag(9193));
    SetNetworkconnectedEventFlagID(1028102801, ON);
    EndEvent();
});

$Event(1028102810, Default, function(chrEntityId) {
    EndIf(EventFlag(1028100800));
    WaitFor(EventFlag(1028102801) || EventFlag(9193));
    SetSpEffect(chrEntityId, 10260);
    WaitFor(CharacterHasSpEffect(chrEntityId, 10278));
    ChangeWeather(Weather.None, -1, false);
    ClearSpEffect(20000, 4213);
    SetEventFlagID(1028102802, ON);
    SetEventFlagID(1028102803, OFF);
    EndEvent();
});

$Event(1028102820, Default, function(chrEntityId) {
    EnableNetworkSync();
    EndIf(EventFlag(1028100800));
    WaitFor(EventFlag(1028102802));
    DisableCharacterCollision(chrEntityId);
    DisableCharacter(chrEntityId);
    DisableCharacterAI(chrEntityId);
    EndEvent();
});

$Event(1028102830, Default, function(chrEntityId) {
    EndIf(EventFlag(chrEntityId));
    WaitFor(CharacterHPValue(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    PlaySE(chrEntityId, SoundType.SFX, 888880000);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, 1039100802, 0, 0);
    DisplayTextEffectId(1000);
    SetEventFlagID(chrEntityId, ON);
});

$Event(1028102840, Default, function(areaEntityId, chrEntityId) {
    if (!EventFlag(1028102802)) {
        if (!EventFlag(1028100800)) {
            WaitFor(InArea(20000, areaEntityId));
            EndIf(CharacterDead(chrEntityId) || EventFlag(1028102802));
            EndIf(
                EventFlag(1039102800)
                    || EventFlag(1029102800)
                    || EventFlag(1039102820)
                    || EventFlag(9193));
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

$Event(1028102850, Default, function(chrEntityId, areaEntityId) {
    WaitFor(CharacterDead(chrEntityId) && InArea(20000, areaEntityId));
    ChangeWeather(Weather.None, -1, false);
    WaitFixedTimeSeconds(3);
    ClearSpEffect(20000, 4213);
    EndEvent();
});

$Event(1028102860, Default, function() {
    WaitFor(EventFlag(1028102802));
    ChangeWeather(Weather.None, -1, false);
    WaitFixedTimeSeconds(3);
    ClearSpEffect(20000, 4213);
    EndEvent();
});

$Event(1028102870, Default, function(chrEntityId, areaEntityId) {
    DisableNetworkSync();
    WaitFor(EventFlag(7601) && InArea(20000, areaEntityId));
    if (!CharacterDead(chrEntityId)) {
        if (!(EventFlag(1039102905)
            || EventFlag(1029102905)
            || EventFlag(1039102915)
            || EventFlag(1028102802))) {
            SetSpEffect(20000, 99110);
            WaitFixedTimeSeconds(1);
            RestartEvent();
        }
    }
L0:
    EndEvent();
});

$Event(1028102880, Default, function(chrEntityId, nameId, chrEntityId2) {
    DisableNetworkSync();
    if (!EventFlag(1028100800)) {
        if (!EventFlag(1029102800)) {
            if (!EventFlag(1039102800)) {
                if (!EventFlag(1039102810)) {
                    WaitFor(
                        EventFlag(1028102800) && CharacterAIState(chrEntityId2, AIStateType.Combat));
                    if (!EventFlag(1029102800)) {
                        if (!EventFlag(1039102800)) {
                            if (!EventFlag(1039102810)) {
                                if (!EventFlag(1028102801)) {
                                    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
                                    if (!EventFlag(72450)) {
                                        SetNetworkconnectedEventFlagID(72450, ON);
                                    }
                                    WaitFor(
                                        EventFlag(1028102801)
                                            && CharacterAIState(chrEntityId2, AIStateType.Combat, NotEqual, 1));
                                    DisplayBossHealthBar(Disabled, chrEntityId, 0, nameId);
                                    RestartEvent();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
L0:
    EndEvent();
});

$Event(1028102900, Default, function() {
    WaitFor(CharacterHPValue(1039100802) <= 0 && CharacterAIState(1028100800, AIStateType.Combat));
    ForceCharacterDeath(1028100800, true);
});

$Event(1028102995, Restart, function() {
    CreateReferredDamagePair(1028100800, 1039100802);
});

$Event(1028102210, Restart, function(areaEntityId, eventFlagId) {
    DisableNetworkSync();
    if (!EventFlag(eventFlagId)) {
        WaitFor(InArea(20000, areaEntityId));
        SetEventFlagID(eventFlagId, ON);
        WaitFixedTimeSeconds(0.1);
    }
L0:
    WaitFor(!InArea(20000, areaEntityId));
    SetEventFlagID(eventFlagId, OFF);
    WaitFixedTimeSeconds(0.1);
    RestartEvent();
});
