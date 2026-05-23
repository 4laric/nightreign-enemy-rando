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
        if (EventFlag(48200000)) {
            $InitializeCommonEvent(0, 90055000, 48205200, 1, 48202200, 48200201);
            $InitializeCommonEvent(0, 90055001, 48205200, 1, 48200201, 48200200);
        }
        if (EventFlag(48200001)) {
            $InitializeCommonEvent(0, 90055000, 48205200, 2, 48202200, 48200201);
            $InitializeCommonEvent(0, 90055001, 48205200, 2, 48200201, 48200200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 48200200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 48202200, 48200200);
        $InitializeCommonEvent(0, 99055400, 48202200, 48200200);
        $InitializeCommonEvent(0, 99055300, 48202200, 48200200);
        $InitializeCommonEvent(0, 99055200, 48200200, 48200800, 48200810);
    }
    $InitializeCommonEvent(0, 90065090, 48200800, 48200801, 48200200, 48200205, 48200211, 48200800);
    $InitializeCommonEvent(0, 90065091, 48200800, 48200801, 48200200, 48200211, 48200800);
    $InitializeCommonEvent(0, 90065911, 48200200, 48200800, 790000, 48200801, 48200801, 907900000, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065900, 48200800, 2, 0, 0, 1080, 790000, 907900000, 48200801);
    $InitializeCommonEvent(0, 90015012, 48200800, 48200200);
    $InitializeCommonEvent(1, 90015012, 48200801, 48200200);
    $InitializeCommonEvent(0, 90015020, 48200200, 48200800);
    $InitializeCommonEvent(0, 90065092, 48200800, 48200200, 48200210, 48200211, 48200800);
    $InitializeCommonEvent(0, 90035001, 48205210);
});

$Event(48202800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 0);
    DisplayBossHealthBar(Disabled, chrEntityId, 1, 0);
    DisplayBossHealthBar(Disabled, chrEntityId, 2, 0);
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

$Event(48202810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacter(48200801);
        DisableCharacterCollision(chrEntityId);
        DisableCharacterCollision(48200801);
        ForceCharacterDeath(chrEntityId, false);
        ForceCharacterDeath(48200801, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacter(48200801);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterCollision(48200801);
    DisableCharacterAI(chrEntityId);
    DisableCharacterAI(48200801);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterAI(chrEntityId);
    ForceAnimationPlayback(48200800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(48200801);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48200800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});

$Event(48202820, Restart, function(chrEntityId, spEffectId) {
    CreateNPCPart(chrEntityId, 50, NPCPartType.Part1, 1000, 1, 1, false, false);
    SetNPCPartSEAndSFX(chrEntityId, 50, 125, 110, 106, 110, 106);
    WaitFor(NPCPartHP(chrEntityId, 50) <= 1);
    SetSpEffect(48200800, spEffectId);
    EndEvent();
});

$Event(48202830, Restart, function(chrEntityId, spEffectId) {
    WaitFor((CharacterHasSpEffect(chrEntityId, spEffectId)) || ElapsedSeconds(10));
    ForceAnimationPlayback(48200800, 20000, true, false, false);
});

$Event(48202840, Restart, function(chrEntityId, dummypolyId) {
    WaitFor((CharacterHasSpEffect(48200800, 44100)) || ElapsedSeconds(10));
    WaitFixedTimeSeconds(1.5);
    WarpCharacterAndCopyFloor(chrEntityId, TargetEntityType.Character, 48200800, dummypolyId, 48200800);
    EnableCharacter(48200801);
    EnableCharacterCollision(48200801);
    EnableCharacterAI(48200801);
    ForceAnimationPlayback(48200801, 20000, true, false, false);
    DisplayBossHealthBar(Disabled, 48200800, 0, 907900000);
    DisplayBossHealthBar(Disabled, 48200800, 1, 907900000);
    DisplayBossHealthBar(Disabled, 48200800, 2, 907900000);
    WaitFixedTimeSeconds(1);
    DisplayBossHealthBar(Enabled, 48200801, 0, 907900000);
    RestartEvent();
});
