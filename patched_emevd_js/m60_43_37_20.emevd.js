// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1043370300, 15);
    $InitializeCommonEvent(0, 99055500, 1043370345, 15);
    $InitializeCommonEvent(0, 99055500, 1043370346, 15);
    $InitializeCommonEvent(0, 99055500, 1043370347, 15);
    $InitializeCommonEvent(0, 99055500, 1043370349, 15);
    $InitializeCommonEvent(0, 99055500, 1043370350, 15);
    $InitializeCommonEvent(0, 91005506, 1043375200);
    RegisterBonfire(1043371951, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1043371951, 1043370951);
    $InitializeCommonEvent(0, 90005580, 1043371952, 1043370952, 7655);
    $InitializeCommonEvent(0, 90015000, 1043372901, 1043370851, 907550002, 30, 756020, 8110);
    $InitializeCommonEvent(0, 99055500, 1043370851, 15);
    $InitializeCommonEvent(0, 90015030, 1043372901, 1043370851, 30, 756020, 8110);
    $InitializeCommonEvent(0, 90015002, 0, 1043372901, 1043370850, 1043370851, 1020, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015160, 1043370850, 1043372901);
    $InitializeCommonEvent(0, 90015161, 1043370850, 1043372900);
    $InitializeCommonEvent(0, 90015162, 1043370850, 1043372900, 1043372901);
    $InitializeCommonEvent(0, 90015163, 1043370851, 1043372900, 1043372901, 1043370850);
    $InitializeCommonEvent(0, 90015164, 1043370850, 1043372901);
    $InitializeCommonEvent(0, 9005811, 74000, 1043371801, 5, 0);
    $InitializeEvent(0, 1043372700);
    $InitializeEvent(0, 1043372710, 1043371210, 1043372810, 1043371211);
    $InitializeEvent(1, 1043372710, 1043371211, 1043372811, 1043371210);
    $InitializeCommonEvent(0, 90005910, 1043371800, 7680);
    $InitializeCommonEvent(0, 91005505, 1043372510, 7680);
    $InitializeCommonEvent(0, 90065901, 1043374890);
    $InitializeCommonEvent(0, 90015150, 1043370200, 73063);
    $InitializeCommonEvent(0, 90015151, 1043370200, 74023);
    $InitializeCommonEvent(0, 90015152, 1043370200, 74023);
    $InitializeEvent(0, 1043372200, 1043370300, 1043372201);
    $InitializeEvent(1, 1043372200, 1043370319, 1043372202);
    $InitializeEvent(2, 1043372200, 1043370337, 1043372203);
    $InitializeEvent(3, 1043372200, 1043370326, 1043372204);
    $InitializeCommonEvent(0, 91005503, 1043371500);
    $InitializeCommonEvent(0, 90015140, 1043371220, 200, 9108, 1043371220);
    $InitializeEvent(0, 1043372910);
    $InitializeCommonEvent(0, 90085001, 801, Hero.Executor, 9256, 9256, 1043371260);
    if (1 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9266, 9256, 9256, 1043375260, 1043370260, 0, 0, 0, 20026);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9266, 9256, 9256, 1043375260, 1043370260, 1043370261, 0, 0, 20026);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9266, 9256, 9256, 1043375260, 1043370260, 1043370261, 1043370262, 0, 20026);
    }
    if (4 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9266, 9256, 9256, 1043375260, 1043370260, 1043370261, 1043370262, 1043370263, 20026);
    }
    $InitializeCommonEvent(0, 90085802, 801, 9266, 1043375260);
    $InitializeCommonEvent(0, 90015501, 1043372300, 73992);
});

$Event(1043372200, Restart, function(chrEntityId, areaEntityId) {
    SetSpEffect(chrEntityId, 8081);
    WaitFor(InArea(10000, areaEntityId));
    ClearSpEffect(chrEntityId, 8081);
    WaitFor(!InArea(10000, areaEntityId));
    RestartEvent();
});

$Event(1043372210, Restart, function(attachPointEntityId, eventFlagId) {
    EndIf(EventFlag(eventFlagId));
    WaitFor(EventFlag(9999));
    if (SmallBaseAttached(attachPointEntityId, 45510000)) {
        WaitFor(EventFlag(45510800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46510000)) {
        WaitFor(EventFlag(46510800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46520000)) {
        WaitFor(EventFlag(46520800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46530000)) {
        WaitFor(EventFlag(46530800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46540000)) {
        WaitFor(EventFlag(46540800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46550000)) {
        WaitFor(EventFlag(46550800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46560000)) {
        WaitFor(EventFlag(46560800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46570000)) {
        WaitFor(EventFlag(46570800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46580000)) {
        WaitFor(EventFlag(46580800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46620000)) {
        WaitFor(EventFlag(46620800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46630000)) {
        WaitFor(EventFlag(46630800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46640000)) {
        WaitFor(EventFlag(46640800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46650000)) {
        WaitFor(EventFlag(46650800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46660000)) {
        WaitFor(EventFlag(46660800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46670000)) {
        WaitFor(EventFlag(46670800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46680000)) {
        WaitFor(EventFlag(46680800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46690000)) {
        WaitFor(EventFlag(46690800));
    }
    if (SmallBaseAttached(attachPointEntityId, 46740000)) {
        WaitFor(EventFlag(46740800));
    }
    if (SmallBaseAttached(attachPointEntityId, 49910000)) {
        WaitFor(EventFlag(49910800));
    }
    if (SmallBaseAttached(attachPointEntityId, 49920000)) {
        WaitFor(EventFlag(49920800));
    }
    SetNetworkconnectedEventFlagID(eventFlagId, ON);
});

$Event(1043372700, Restart, function() {
    if (EventFlag(1043370211)) {
        ForceAnimationPlayback(1043371200, 2, true, false, false);
        ForceAnimationPlayback(1043371201, 2, true, false, false);
        EndEvent();
    }
    if (EventFlag(1043370210)) {
        ForceAnimationPlayback(1043371200, 1, true, false, false);
        ForceAnimationPlayback(1043371201, 1, true, false, false);
        WaitFor(ElapsedSeconds(6));
        SetNetworkconnectedEventFlagID(1043370211, ON);
        EndEvent();
    }
    WaitFor(EventFlag(1043370210));
    ForceAnimationPlayback(1043371200, 1, true, false, false);
    ForceAnimationPlayback(1043371201, 1, true, false, false);
    WaitFor(ElapsedSeconds(6));
    SetNetworkconnectedEventFlagID(1043370211, ON);
});

$Event(1043372710, Restart, function(entityId, areaEntityId, entityId2) {
    if (!EventFlag(1043370210)) {
        WaitFor(InArea(20000, areaEntityId));
        EndIf(EventFlag(1043370210));
        ForceAnimationPlayback(entityId, 1, false, false, false);
        ForceAnimationPlayback(entityId2, 1, false, true, false);
        SetNetworkconnectedEventFlagID(1043370210, ON);
    }
    ForceAnimationPlayback(entityId, 2, true, false, false);
    ForceAnimationPlayback(entityId2, 2, true, false, false);
});

$Event(1043372800, Restart, function() {
    if (!EventFlag(1043372830)) {
        DisableCharacter(1043370800);
        DisableCharacterAI(1043370800);
    }
L0:
    EndEvent();
});

$Event(1043372801, Restart, function() {
    if (!EventFlag(1043372830)) {
    }
L0:
    EndEvent();
});

$Event(1043372810, Restart, function() {
    if (!EventFlag(1043372830)) {
        WaitFor(
            EventFlag(1043372801)
                && (InArea(10000, 1043372650)
                    || InArea(10001, 1043372650)
                    || InArea(10002, 1043372650)));
        EnableCharacter(1043370800);
        ForceAnimationPlayback(1043370800, 20000, false, false, false);
        EnableCharacterAI(1043370800);
    }
L0:
    EndEvent();
});

$Event(1043372811, Restart, function() {
    DisableNetworkSync();
    if (!EventFlag(1043372830)) {
        WaitFor(EventFlag(1043372810) && EntityInRadiusOfEntity(20000, 1043370800, 50, 1));
        DisplayBossHealthBar(Enabled, 1043370800, 0, 904980601);
        SetSpEffect(20000, 99825);
        WaitFor(EventFlag(1043372810) && !EntityInRadiusOfEntity(20000, 1043370800, 50, 1));
        DisplayBossHealthBar(Disabled, 1043370800, 0, 904980601);
        ClearSpEffect(20000, 99825);
        RestartEvent();
    }
L0:
    EndEvent();
});

$Event(1043372820, Restart, function() {
    if (!EventFlag(1043372830)) {
        WaitFor(EventFlag(1043372810));
        SetSpEffect(0, 0);
    }
L0:
    EndEvent();
});

$Event(1043372830, Restart, function() {
    WaitFor(!EventFlag(1043372830) && EventFlag(1043372820) && CharacterHPValue(1043370800) <= 0);
    PlaySE(1043370800, SoundType.SFX, 888880000);
    HandleMinibossDefeat(1043370800);
    DisplayBossHealthBar(Disabled, 1043370800, 0, 904980601);
    SetNetworkconnectedEventFlagID(1043370800, ON);
});

$Event(1043372840, Default, function() {
    WaitFor(!EventFlag(1043372840) && EventFlag(1043372830) && EventFlag(1043374590));
    DisplayTextEffectId(2200);
});

$Event(1043372910, Restart, function() {
    WaitFor(SmallBaseAttached(1042372999, 30300000));
    EnableAsset(1043371900);
    EnableAsset(1043371901);
    EnableAsset(1043371902);
});
