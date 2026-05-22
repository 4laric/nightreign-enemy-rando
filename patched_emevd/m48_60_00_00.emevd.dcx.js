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
        if (EventFlag(48600000)) {
            $InitializeCommonEvent(0, 90055000, 48605200, 1, 48602200, 48600201);
            $InitializeCommonEvent(0, 90055001, 48605200, 1, 48600201, 48600200);
        }
        if (EventFlag(48600001)) {
            $InitializeCommonEvent(0, 90055000, 48605200, 2, 48602200, 48600201);
            $InitializeCommonEvent(0, 90055001, 48605200, 2, 48600201, 48600200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 48600200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 48602200, 48600200);
        $InitializeCommonEvent(0, 99055400, 48602200, 48600200);
        $InitializeCommonEvent(0, 99055300, 48602200, 48600200);
        $InitializeCommonEvent(0, 99055200, 48600200, 48600800, 48600810);
    }
    $InitializeCommonEvent(0, 90065050, 48600200, 48600205, 48600800, 920200, 48605800, 48600800, 903251600, 48600810, 904351000, 48600820, 904351000, 48600811, 48600821);
    $InitializeCommonEvent(0, 90065911, 48600200, 48600800, 920200, 48605800, 48600800, 903251600, 48600810, 904351000, 48600820, 904351000, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 48600800, 2, 0, 0, 1050, 920200, 903251600, 48600800);
    }
    $InitializeCommonEvent(0, 90065051, 48600800, 48605805, 48605806, 48600800);
    $InitializeCommonEvent(0, 90015011, 48605899, 48600200, 48600800);
    $InitializeCommonEvent(0, 90015012, 48605899, 48600200);
    $InitializeCommonEvent(0, 90015020, 48600200, 48600800);
    $InitializeCommonEvent(0, 90015008, 48600205, 48600800, 920200, 48600800, 13771, 0);
    $InitializeCommonEvent(0, 90035001, 48605800);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065052, 48600800, 48600801, 48600805, 13733, 100, 48600200, 48600800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065056, 48600800, 48600801, 48600805, 13733, 100, 48602290, 48602291, 48600200, 48600800);
    }
    $InitializeCommonEvent(0, 90065053, 48600801, 48600805, 48600200, 48600800);
    $InitializeCommonEvent(0, 90065054, 48600810, 48600811, 48600200, 48600800);
    $InitializeCommonEvent(0, 90065055, 48600800, 48600810, 13733, 48600200, 48600800);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065052, 48600800, 48600802, 48600806, 13734, 101, 48600200, 48600800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065056, 48600800, 48600802, 48600806, 13734, 101, 48602290, 48602292, 48600200, 48600800);
    }
    $InitializeCommonEvent(0, 90065053, 48600802, 48600806, 48600200, 48600800);
    $InitializeCommonEvent(0, 90065054, 48600820, 48600821, 48600200, 48600800);
    $InitializeCommonEvent(0, 90065055, 48600800, 48600820, 13734, 48600200, 48600800);
    if (1 != 0) {
        $InitializeCommonEvent(0, 90065920, 48600800, 7310);
        $InitializeCommonEvent(0, 90065920, 48600810, 7311);
        $InitializeCommonEvent(0, 90065920, 48600811, 7311);
        $InitializeCommonEvent(0, 90065920, 48600820, 7311);
        $InitializeCommonEvent(0, 90065920, 48600821, 7311);
        $InitializeCommonEvent(0, 90065920, 48605805, 7311);
        $InitializeCommonEvent(0, 90065920, 48605806, 7311);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 48602200, 48600800);
        $InitializeCommonEvent(0, 90015023, 48600200, 40, 0, 48605800, 48600800, 903251600, 48600810, 904351000, 48600820, 904351000);
        $InitializeCommonEvent(0, 90015030, 48600200, 48605800, 40, 920200, 0);
        $InitializeCommonEvent(0, 90015002, 0, 48600200, 48600800, 48605800, 1020, 920200, 110320, 903251600, 48600800);
        $InitializeCommonEvent(0, 90015470, 48602200, 48600200, 48600800, 48605899, 0, 0, 48605800);
        $InitializeCommonEvent(0, 90065057, 48600800, 48600800);
        $InitializeCommonEvent(0, 90065057, 48600810, 48600800);
        $InitializeCommonEvent(0, 90065057, 48600811, 48600800);
        $InitializeCommonEvent(0, 90065057, 48600820, 48600800);
        $InitializeCommonEvent(0, 90065057, 48600821, 48600800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 48605899, 48600200, 48600800, 48602200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 48602200, 48600800);
        $InitializeCommonEvent(0, 90015460, 48602200, 48600810);
        $InitializeCommonEvent(0, 90015460, 48602200, 48600811);
        $InitializeCommonEvent(0, 90015460, 48602200, 48600820);
        $InitializeCommonEvent(0, 90015460, 48602200, 48600821);
        $InitializeCommonEvent(0, 90015460, 48602200, 48600801);
        $InitializeCommonEvent(0, 90015460, 48602200, 48600805);
        $InitializeCommonEvent(0, 90015460, 48602200, 48600802);
        $InitializeCommonEvent(0, 90015460, 48602200, 48600806);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 48602200, 48600800);
        $InitializeCommonEvent(0, 90015475, 48602200, 48600810);
        $InitializeCommonEvent(0, 90015475, 48602200, 48600811);
        $InitializeCommonEvent(0, 90015475, 48602200, 48600820);
        $InitializeCommonEvent(0, 90015475, 48602200, 48600821);
        $InitializeCommonEvent(0, 90015475, 48602200, 48600801);
        $InitializeCommonEvent(0, 90015475, 48602200, 48600805);
        $InitializeCommonEvent(0, 90015475, 48602200, 48600802);
        $InitializeCommonEvent(0, 90015475, 48602200, 48600806);
    }
    $InitializeCommonEvent(0, 90035001, 48600800);
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48600000, 48600300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48600000, 48600300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48600000, 48600300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48600000, 48600300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48600000, 48600300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48600000, 48600300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48600000, 48600301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48600000, 48600301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48600000, 48600301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48600000, 48600301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48600000, 48600301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48600000, 48600301);
    }
});

$Event(48602300, Restart, function(spEffectId, chrEntityId, chrEntityId2, spEffectId2) {
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

$Event(48602310, Restart, function(chrEntityId, chrEntityId2, chrEntityId3, dummypolyId, spEffectId) {
    WaitFor((CharacterHasSpEffect(chrEntityId, 13744)) || ElapsedSeconds(10));
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

$Event(48602320, Restart, function(spEffectId, chrEntityId, chrEntityId2, spEffectId2) {
    WaitFor((CharacterHasSpEffect(chrEntityId, 13731)) || ElapsedSeconds(10));
    WaitFixedTimeSeconds(0.5);
    DisableCharacter(chrEntityId);
    DisableCharacter(chrEntityId2);
    SetSpEffect(0, spEffectId);
    SetSpEffect(0, spEffectId2);
    RestartEvent();
});

$Event(48602330, Restart, function(chrEntityId, chrEntityId2, spEffectId) {
    WaitFor(HPRatio(chrEntityId2) <= 0);
    SetSpEffect(chrEntityId, spEffectId);
});

$Event(48602800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFor(HPRatio(48600810) <= 0);
    WaitFor(HPRatio(48600820) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 0);
    DisplayBossHealthBar(Disabled, 48600810, 1, 904351000);
    DisplayBossHealthBar(Disabled, 48600820, 2, 904351000);
    DisableCharacterCollision(48600810);
    DisableCharacterCollision(48600820);
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

$Event(48602810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacter(48600810);
        DisableCharacter(48600820);
        DisableCharacterCollision(chrEntityId);
        DisableCharacterCollision(48600810);
        DisableCharacterCollision(48600820);
        ForceCharacterDeath(chrEntityId, false);
        ForceCharacterDeath(48600810, false);
        ForceCharacterDeath(48600820, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacter(48600810);
    DisableCharacter(48600820);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterCollision(48600810);
    DisableCharacterCollision(48600820);
    DisableCharacterAI(chrEntityId);
    DisableCharacterAI(48600810);
    DisableCharacterAI(48600820);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacter(48600810);
    EnableCharacter(48600820);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterCollision(48600810);
    EnableCharacterCollision(48600820);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(48600810);
    EnableCharacterAI(48600820);
    ForceAnimationPlayback(48600800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(48600810);
    DisableCharacterHPBarDisplay(48600820);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(48600810);
    EnableCharacterAI(48600820);
    SetNetworkUpdateRate(48600800, true, CharacterUpdateFrequency.AlwaysUpdate);
    SetNetworkUpdateRate(48600810, true, CharacterUpdateFrequency.AlwaysUpdate);
    SetNetworkUpdateRate(48600820, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
    DisplayBossHealthBar(Enabled, 48600810, 1, 904351000);
    DisplayBossHealthBar(Enabled, 48600820, 2, 904351000);
});

$Event(48602820, Restart, function(chrEntityId, spEffectId) {
    WaitFor((CharacterHasSpEffect(chrEntityId, spEffectId)) || ElapsedSeconds(10));
    ForceCharacterDeath(48600811, true);
});

$Event(48602821, Restart, function(chrEntityId, spEffectId) {
    WaitFor((CharacterHasSpEffect(chrEntityId, spEffectId)) || ElapsedSeconds(10));
    ForceCharacterDeath(48600821, true);
});
