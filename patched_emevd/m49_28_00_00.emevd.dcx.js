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
        if (EventFlag(49280000)) {
            $InitializeCommonEvent(0, 90055000, 49285200, 1, 49282200, 49280201);
            $InitializeCommonEvent(0, 90055001, 49285200, 1, 49280201, 49280200);
        }
        if (EventFlag(49280001)) {
            $InitializeCommonEvent(0, 90055000, 49285200, 2, 49282200, 49280201);
            $InitializeCommonEvent(0, 90055001, 49285200, 2, 49280201, 49280200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49280200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49282200, 49280200);
        $InitializeCommonEvent(0, 99055400, 49282200, 49280200);
        $InitializeCommonEvent(0, 99055300, 49282200, 49280200);
        $InitializeCommonEvent(0, 99055200, 49280200, 49280800, 49280810);
    }
    $InitializeCommonEvent(0, 90065110, 49285800, 49280800, 49280810, 49285801, 49280200, 49280205, 49280800, 49280801, 49280802, 49280801, 49280811);
    $InitializeCommonEvent(0, 90065911, 49280200, 49280800, 921000, 49285800, 49280800, 903150608, 49280810, 903150609, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49280800, 1, 0, 0, 1050, 921000, 903150610, 49280800);
    }
    $InitializeCommonEvent(0, 90065111, 49280800, 49280801, 49280200, 49280800);
    $InitializeCommonEvent(0, 90065111, 49280810, 49280811, 49280200, 49280800);
    $InitializeCommonEvent(0, 90065112, 49280800, 49280801, 49280200, 49280800);
    $InitializeCommonEvent(0, 90065112, 49280810, 49280811, 49280200, 49280800);
    $InitializeCommonEvent(0, 90065113, 49280801, 49280800);
    $InitializeCommonEvent(1, 90065113, 49280802, 49280810);
    $InitializeCommonEvent(0, 90015012, 49285800, 49280200);
    $InitializeCommonEvent(1, 90015012, 49285801, 49280200);
    $InitializeCommonEvent(0, 90015020, 49280200, 49280800);
    $InitializeCommonEvent(0, 90015008, 49280205, 49280800, 921000, 49285800, 0, 0);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49282200, 49280800);
        $InitializeCommonEvent(0, 90015023, 49280200, 40, 0, 49285800, 49280800, 903150608, 49280810, 903150609, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49280200, 49285800, 40, 921000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49280200, 49280800, 49285800, 1020, 921000, 110320, 903150608, 49280800);
        $InitializeCommonEvent(0, 90015470, 49282200, 49280200, 49280800, 49285800, 49285801, 0, 49285800);
        $InitializeCommonEvent(0, 90015478, 49280800, 49280800);
        $InitializeCommonEvent(0, 90015478, 49280810, 49280800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 49285800, 49280200, 49280800, 49282200);
        $InitializeCommonEvent(0, 90015446, 49285801, 49280200, 49280800, 49282200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 49282200, 49280800);
        $InitializeCommonEvent(0, 90015460, 49282200, 49280810);
        $InitializeCommonEvent(0, 90015460, 49282200, 49280801);
        $InitializeCommonEvent(0, 90015460, 49282200, 49280811);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49282200, 49280800);
        $InitializeCommonEvent(0, 90015475, 49282200, 49280810);
        $InitializeCommonEvent(0, 90015475, 49282200, 49280801);
        $InitializeCommonEvent(0, 90015475, 49282200, 49280811);
    }
    $InitializeCommonEvent(0, 90035001, 49280800);
    if (1 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49280000, 49280300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49280000, 49280300);
    }
    if (1 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49280000, 49280300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49280000, 49280300);
    }
    if (1 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49280000, 49280300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49280000, 49280300);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49280000, 49280301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49280000, 49280301);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49280000, 49280301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49280000, 49280301);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49280000, 49280301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49280000, 49280301);
    }
});

$Event(49282800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3, chrEntityId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFor(HPRatio(chrEntityId3) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 903150600);
    DisplayBossHealthBar(Disabled, chrEntityId3, 1, 903150600);
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
    DisableCharacter(chrEntityId3);
});

$Event(49282810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5, chrEntityId2) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacter(chrEntityId2);
        DisableCharacterCollision(chrEntityId);
        DisableCharacterCollision(chrEntityId2);
        ForceCharacterDeath(chrEntityId, false);
        ForceCharacterDeath(chrEntityId2, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacter(chrEntityId2);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterCollision(chrEntityId2);
    DisableCharacterAI(chrEntityId);
    DisableCharacterAI(chrEntityId2);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacter(chrEntityId2);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterCollision(chrEntityId2);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(chrEntityId2);
    ForceAnimationPlayback(48600800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(chrEntityId2);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(chrEntityId2);
    SetNetworkUpdateRate(48600800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
    DisplayBossHealthBar(Enabled, chrEntityId2, 0, nameId);
});
