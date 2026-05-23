// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1045360800, 15);
    $InitializeCommonEvent(0, 90005580, 1045361950, 1045360950, 7659);
    $InitializeCommonEvent(0, 9005810, 1045360800, 1045360951, 1045361951, 5);
    $InitializeCommonEvent(0, 90015005, 1045361951, 1045360951, 1045360800);
    $InitializeCommonEvent(0, 90065901, 1045364890);
    $InitializeCommonEvent(0, 90005910, 1045361800, 7684);
    $InitializeCommonEvent(0, 91005505, 1045362500, 7684);
    $InitializeCommonEvent(0, 90005211, 1045360350, 30000, 20000, 1045362350, 2, 1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015150, 1045360200, 73074);
    $InitializeCommonEvent(0, 90015151, 1045360200, 74034);
    $InitializeCommonEvent(0, 90015152, 1045360200, 74034);
    $InitializeCommonEvent(0, 90015150, 1045360201, 73075);
    $InitializeCommonEvent(0, 90015151, 1045360201, 74035);
    $InitializeCommonEvent(0, 90015152, 1045360201, 74035);
    $InitializeCommonEvent(0, 91005503, 1045361500);
    $InitializeCommonEvent(0, 91005503, 1045361501);
    $InitializeCommonEvent(0, 91005503, 1045361502);
    $InitializeCommonEvent(0, 90005904, 0, 1045361550, 100, 6101);
    $InitializeEvent(0, 1045362900);
    $InitializeCommonEvent(0, 90085612, 602, Hero.Revenant, 9248, 9228, 1045360280, 8463);
    if (1 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9238, 9228, 9228, 1045365280, 1045360281, 0, 0, 0, 20026);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9238, 9228, 9228, 1045365280, 1045360281, 1045360282, 0, 0, 20026);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9238, 9228, 9228, 1045365280, 1045360281, 1045360282, 1045360283, 0, 20026);
    }
    if (4 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9238, 9228, 9228, 1045365280, 1045360281, 1045360282, 1045360283, 1045360284, 20026);
    }
    $InitializeCommonEvent(0, 90085613, 602, 9238, 9228, 9228, 1045365280);
    $InitializeCommonEvent(0, 90085614, 602, 9238, 1045366280, 1045360280, 8463);
});

$Event(50, Default, function() {
    $InitializeCommonEvent(0, 90005250, 1045360280, 1045362280, 2, 3025);
});

$Event(1045362900, Restart, function() {
    WaitFor(SmallBaseAttached(1045362999, 30300000));
    EnableAsset(1045361900);
});
