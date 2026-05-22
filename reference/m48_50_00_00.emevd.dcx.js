// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    DCX_KRAK
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    if (IsMapVariation(0)) {
        if (EventFlag(48500000)) {
            $InitializeCommonEvent(0, 90055000, 48505200, 1, 48502200, 48500201);
            $InitializeCommonEvent(0, 90055001, 48505200, 1, 48500201, 48500200);
        }
        if (EventFlag(48500001)) {
            $InitializeCommonEvent(0, 90055000, 48505200, 2, 48502200, 48500201);
            $InitializeCommonEvent(0, 90055001, 48505200, 2, 48500201, 48500200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 48500200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 48502200, 48500200);
    }
    $InitializeCommonEvent(0, 90065050, 48500200, 48500205, 48500800, 920200, 48505800, 48500800, 903250600, 48500810, 904351000, 48500820, 904351000, 48500811, 48500821);
    $InitializeCommonEvent(0, 90065911, 48500200, 48500800, 920200, 48505800, 48500800, 903250600, 48500810, 904351000, 48500820, 904351000, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 48500800, 2, 0, 0, 1050, 920200, 903250600, 48500800);
    }
    $InitializeCommonEvent(0, 90065051, 48500800, 48505801, 48505802, 48500800);
    $InitializeCommonEvent(0, 90015011, 48505899, 48500200, 48500800);
    $InitializeCommonEvent(0, 90015012, 48505899, 48500200);
    $InitializeCommonEvent(0, 90015020, 48500200, 48500800);
    $InitializeCommonEvent(0, 90015008, 48500205, 48500800, 920200, 48500800, 13708, 0);
    $InitializeCommonEvent(0, 90035001, 48505800);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065052, 48500800, 48500801, 48500805, 13733, 100, 48500200, 48500800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065056, 48500800, 48500801, 48500805, 13733, 100, 48502290, 48502291, 48500200, 48500800);
    }
    $InitializeCommonEvent(0, 90065053, 48500801, 48500805, 48500200, 48500800);
    $InitializeCommonEvent(0, 90065054, 48500810, 48500811, 48500200, 48500800);
    $InitializeCommonEvent(0, 90065055, 48500800, 48500810, 13733, 48500200, 48500800);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065052, 48500800, 48500802, 48500806, 13734, 101, 48500200, 48500800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065056, 48500800, 48500802, 48500806, 13734, 101, 48502290, 48502292, 48500200, 48500800);
    }
    $InitializeCommonEvent(0, 90065053, 48500802, 48500806, 48500200, 48500800);
    $InitializeCommonEvent(0, 90065054, 48500820, 48500821, 48500200, 48500800);
    $InitializeCommonEvent(0, 90065055, 48500800, 48500820, 13734, 48500200, 48500800);
    if (0 != 0) {
        $InitializeCommonEvent(0, 90065920, 48500800, 7310);
        $InitializeCommonEvent(0, 90065920, 48500810, 7311);
        $InitializeCommonEvent(0, 90065920, 48500811, 7311);
        $InitializeCommonEvent(0, 90065920, 48500820, 7311);
        $InitializeCommonEvent(0, 90065920, 48500821, 7311);
        $InitializeCommonEvent(0, 90065920, 48505801, 7311);
        $InitializeCommonEvent(0, 90065920, 48505802, 7311);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 48502200, 48500800);
        $InitializeCommonEvent(0, 90015023, 48500200, 40, 0, 48505800, 48500800, 903250600, 48500810, 904351000, 48500820, 904351000);
        $InitializeCommonEvent(0, 90015030, 48500200, 48505800, 40, 920200, 0);
        $InitializeCommonEvent(0, 90015002, 0, 48500200, 48500800, 48505800, 1020, 920200, 110320, 903250600, 48500800);
        $InitializeCommonEvent(0, 90015470, 48502200, 48500200, 48500800, 48505899, 0, 0, 48505800);
        $InitializeCommonEvent(0, 90065057, 48500800, 48500800);
        $InitializeCommonEvent(0, 90065057, 48500810, 48500800);
        $InitializeCommonEvent(0, 90065057, 48500811, 48500800);
        $InitializeCommonEvent(0, 90065057, 48500820, 48500800);
        $InitializeCommonEvent(0, 90065057, 48500821, 48500800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 48505899, 48500200, 48500800, 48502200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 48502200, 48500800);
        $InitializeCommonEvent(0, 90015460, 48502200, 48500810);
        $InitializeCommonEvent(0, 90015460, 48502200, 48500811);
        $InitializeCommonEvent(0, 90015460, 48502200, 48500820);
        $InitializeCommonEvent(0, 90015460, 48502200, 48500821);
        $InitializeCommonEvent(0, 90015460, 48502200, 48500801);
        $InitializeCommonEvent(0, 90015460, 48502200, 48500805);
        $InitializeCommonEvent(0, 90015460, 48502200, 48500802);
        $InitializeCommonEvent(0, 90015460, 48502200, 48500806);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 48502200, 48500800);
        $InitializeCommonEvent(0, 90015475, 48502200, 48500810);
        $InitializeCommonEvent(0, 90015475, 48502200, 48500811);
        $InitializeCommonEvent(0, 90015475, 48502200, 48500820);
        $InitializeCommonEvent(0, 90015475, 48502200, 48500821);
        $InitializeCommonEvent(0, 90015475, 48502200, 48500801);
        $InitializeCommonEvent(0, 90015475, 48502200, 48500805);
        $InitializeCommonEvent(0, 90015475, 48502200, 48500802);
        $InitializeCommonEvent(0, 90015475, 48502200, 48500806);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48500000, 48500300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48500000, 48500300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48500000, 48500300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48500000, 48500300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48500000, 48500300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48500000, 48500300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48500000, 48500301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48500000, 48500301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48500000, 48500301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48500000, 48500301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48500000, 48500301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48500000, 48500301);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015476, 10002, 48502200);
        $InitializeCommonEvent(0, 90015476, 10003, 48502200);
        $InitializeCommonEvent(0, 90015476, 10004, 48502200);
    }
});

$Event(48502300, Restart, function(spEffectId, chrEntityId, chrEntityId2, spEffectId2) {
    EnableCharacterImmortality(chrEntityId);
    EnableCharacterImmortality(chrEntityId2);
    DisableLockOnPoint(chrEntityId, 220);
    DisableLockOnPoint(chrEntityId2, 220);
    WaitFor(ElapsedFrames(1));
    DisableCharacter(chrEntityId);
    DisableCharacter(chrEntityId2);
    SetSpEffect(0, spEffectId);
    SetSpEffect(0, spEffectId2);
});

$Event(48502310, Restart, function(chrEntityId, chrEntityId2, chrEntityId3, dummypolyId, spEffectId) {
    WaitFor(EventFlag(48502300) && CharacterHasSpEffect(chrEntityId, 13744));
    SetSpEffect(chrEntityId2, 13745);
    SetSpEffect(chrEntityId3, 13745);
    sp = CharacterHasSpEffect(chrEntityId, spEffectId);
    sp2 = !CharacterHasSpEffect(chrEntityId, spEffectId);
    GotoIf(L0, sp);
    GotoIf(L1, sp2);
L0:
    EnableCharacter(chrEntityId2);
    EnableCharacter(chrEntityId3);
    WaitFixedTimeFrames(1);
    SetCharacterBackreadState(chrEntityId2, false);
    SetCharacterBackreadState(chrEntityId3, false);
    WarpCharacterAndCopyFloorUnknown200489(chrEntityId3, TargetEntityType.Character, chrEntityId, dummypolyId, chrEntityId, -1, -1);
    RestartEvent();
L1:
    RestartEvent();
});

$Event(48502320, Restart, function(spEffectId, chrEntityId, chrEntityId2, spEffectId2) {
    WaitFor(EventFlag(48502310) && CharacterHasSpEffect(chrEntityId, 13731));
    WaitFixedTimeSeconds(0.5);
    DisableCharacter(chrEntityId);
    DisableCharacter(chrEntityId2);
    SetSpEffect(0, spEffectId);
    SetSpEffect(0, spEffectId2);
    RestartEvent();
});

$Event(45602330, Restart, function(chrEntityId, chrEntityId2, spEffectId) {
    WaitFor(HPRatio(chrEntityId2) <= 0);
    SetSpEffect(chrEntityId, spEffectId);
});

$Event(48502800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFor(HPRatio(48500810) <= 0);
    WaitFor(HPRatio(48500820) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 0);
    DisplayBossHealthBar(Disabled, 48500810, 1, 904351000);
    DisplayBossHealthBar(Disabled, 48500820, 2, 904351000);
    DisableCharacterCollision(48500810);
    DisableCharacterCollision(48500820);
    if (assetEntityId != 0) {
        EnableAsset(assetEntityId);
    }
    if (chrEntityId2 != 0) {
        EnableCharacter(chrEntityId2);
    }
    if (!EventFlag(eventFlagId3)) {
        SetEventFlagID(eventFlagId, ON);
        EndEvent();
    }
    SetEventFlagID(eventFlagId2, ON);
    WaitFor(ElapsedSeconds(3));
    DisableCharacter(chrEntityId);
});

$Event(48502810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacter(48500810);
        DisableCharacter(48500820);
        DisableCharacterCollision(chrEntityId);
        DisableCharacterCollision(48500810);
        DisableCharacterCollision(48500820);
        ForceCharacterDeath(chrEntityId, false);
        ForceCharacterDeath(48500810, false);
        ForceCharacterDeath(48500820, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacter(48500810);
    DisableCharacter(48500820);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterCollision(48500810);
    DisableCharacterCollision(48500820);
    DisableCharacterAI(chrEntityId);
    DisableCharacterAI(48500810);
    DisableCharacterAI(48500820);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor(EventFlag(eventFlagId3));
    SpawnOneshotSFX(TargetEntityType.Character, chrEntityId, 900, 690047);
    SetSpEffect(20000, 99160);
    WaitFixedTimeSeconds(4);
    EnableCharacter(chrEntityId);
    EnableCharacter(48500810);
    EnableCharacter(48500820);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterCollision(48500810);
    EnableCharacterCollision(48500820);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(48500810);
    EnableCharacterAI(48500820);
    ForceAnimationPlayback(48500800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(48500810);
    DisableCharacterHPBarDisplay(48500820);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(48500810);
    EnableCharacterAI(48500820);
    SetNetworkUpdateRate(48500800, true, CharacterUpdateFrequency.AlwaysUpdate);
    SetNetworkUpdateRate(48500810, true, CharacterUpdateFrequency.AlwaysUpdate);
    SetNetworkUpdateRate(48500820, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
    DisplayBossHealthBar(Enabled, 48500810, 1, 904351000);
    DisplayBossHealthBar(Enabled, 48500820, 2, 904351000);
});

$Event(48502820, Restart, function(chrEntityId, spEffectId) {
    WaitFor(CharacterHasSpEffect(chrEntityId, spEffectId));
    ForceCharacterDeath(48500811, true);
});

$Event(48502821, Restart, function(chrEntityId, spEffectId) {
    WaitFor(CharacterHasSpEffect(chrEntityId, spEffectId));
    ForceCharacterDeath(48500821, true);
});


