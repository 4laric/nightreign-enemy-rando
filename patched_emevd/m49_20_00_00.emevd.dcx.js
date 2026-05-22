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
        if (EventFlag(49200000)) {
            $InitializeCommonEvent(0, 90055000, 49205200, 1, 49202200, 49200201);
            $InitializeCommonEvent(0, 90055001, 49205200, 1, 49200201, 49200200);
        }
        if (EventFlag(49200001)) {
            $InitializeCommonEvent(0, 90055000, 49205200, 2, 49202200, 49200201);
            $InitializeCommonEvent(0, 90055001, 49205200, 2, 49200201, 49200200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49200200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49202200, 49200200);
        $InitializeCommonEvent(0, 99055400, 49202200, 49200200);
        $InitializeCommonEvent(0, 99055300, 49202200, 49200200);
        $InitializeCommonEvent(0, 99055200, 49200200, 49200800, 49200810);
    }
    $InitializeCommonEvent(0, 90065910, 49200200, 49200205, 49200800, 920800, 690047, 49205210, 49200800, 904680603, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49200200, 49200800, 920800, 49205210, 49200800, 904680603, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49200800, 2, 0, 0, 1050, 920800, 904680603, 49200800);
    }
    $InitializeCommonEvent(0, 90015012, 49205210, 49200200);
    $InitializeCommonEvent(1, 90015012, 0, 49200200);
    $InitializeCommonEvent(0, 90015020, 49200200, 49200800);
    $InitializeCommonEvent(0, 90015008, 49200205, 49200800, 920800, 49200800, 16495, 0);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49202200, 49200800);
        $InitializeCommonEvent(0, 90015023, 49200200, 40, 0, 49205210, 49200800, 904680603, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49200200, 49205210, 40, 920800, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49200200, 49200800, 49205210, 1020, 920800, 110320, 904680603, 49200800);
        $InitializeCommonEvent(0, 90015470, 49202200, 49200200, 49200800, 49205210, 0, 0, 49205210);
        $InitializeCommonEvent(0, 90015446, 49205210, 49200200, 49200800, 49202200);
        $InitializeCommonEvent(0, 90015460, 49202200, 49200800);
        $InitializeCommonEvent(0, 90015460, 49202200, 0);
        $InitializeCommonEvent(0, 90015460, 49202200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49202200, 49200800);
        $InitializeCommonEvent(0, 90015475, 49202200, 0);
        $InitializeCommonEvent(0, 90015475, 49202200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 49200800);
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49200000, 49200300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49200000, 49200300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49200000, 49200300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49200000, 49200300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49200000, 49200300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49200000, 49200300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49200000, 49200301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49200000, 49200301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49200000, 49200301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49200000, 49200301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49200000, 49200301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49200000, 49200301);
    }
});

$Event(492002800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 0);
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

$Event(49202810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacterCollision(chrEntityId);
        ForceCharacterDeath(chrEntityId, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterAI(chrEntityId);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterAI(chrEntityId);
    ForceAnimationPlayback(49200800, 20009, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(49200801);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(49200800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
